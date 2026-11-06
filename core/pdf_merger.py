import os
import tempfile
from typing import Callable, Iterable, Optional

from pypdf import PdfReader, PdfWriter


ProgressCallback = Callable[[int, int, str], None]


class PdfMergerService:
    def merge(
        self,
        input_paths: Iterable[str],
        output_path: str,
        progress_callback: Optional[ProgressCallback] = None,
        *,
        overwrite: bool = False,
        page_orders: Optional[list[Optional[list[int]]]] = None,
    ) -> None:
        """
        Merge PDFs using pypdf.PdfWriter.
        progress_callback(current_index, total_count, filename)
        """
        paths = list(input_paths)
        if not paths:
            raise ValueError("Add at least one PDF before merging.")
        if page_orders is not None and len(page_orders) != len(paths):
            raise ValueError("Provide one page order per input PDF.")
        output_path = os.path.abspath(output_path)
        for path in paths:
            if (os.path.normcase(os.path.realpath(path)) ==
                    os.path.normcase(os.path.realpath(output_path)) or
                    (os.path.exists(output_path) and os.path.samefile(path, output_path))):
                raise ValueError("The output must not replace an input PDF.")
        if not overwrite and os.path.exists(output_path):
            raise FileExistsError("The output already exists. Enable overwrite to replace it.")
        total = len(paths)
        writer = PdfWriter()
        temporary_path = None
        try:
            for index, path in enumerate(paths, start=1):
                with open(path, "rb") as source:
                    reader = PdfReader(source)
                    pages = page_orders[index - 1] if page_orders is not None else None
                    if pages is not None and (not pages or any(
                        type(page) is not int or page < 0 or page >= len(reader.pages)
                        for page in pages
                    )):
                        raise ValueError(f"Invalid page selection for {os.path.basename(path)}.")
                    writer.append(reader, pages=pages)
                if progress_callback:
                    progress_callback(index, total, path)

            # Write beside the destination so publishing is atomic on its filesystem.
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=os.path.dirname(output_path), prefix=".pdf-merger-",
                suffix=".tmp", delete=False,
            ) as output_handle:
                temporary_path = output_handle.name
                writer.write(output_handle)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            if overwrite:
                os.replace(temporary_path, output_path)
            elif os.name == "nt":
                # Windows rename refuses existing destinations, including on FAT/exFAT.
                os.rename(temporary_path, output_path)
            else:
                # Unlike a preflight exists() check, this cannot overwrite a racing file.
                os.link(temporary_path, output_path)
        finally:
            writer.close()
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def split(self, input_path: str, output_paths: list[str], groups: list[list[int]],
              progress_callback: Optional[ProgressCallback] = None, *,
              overwrite: bool = False) -> None:
        if not groups or len(groups) != len(output_paths):
            raise ValueError("Provide one output file for each split group.")
        normalized = [os.path.normcase(os.path.realpath(path)) for path in output_paths]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Split output names must be unique.")
        # Validate the complete plan before creating any files.
        with open(input_path, "rb") as source:
            count = len(PdfReader(source).pages)
        for output, group in zip(output_paths, groups):
            if not group or any(type(p) is not int or p < 0 or p >= count for p in group):
                raise ValueError("A split group contains invalid pages.")
            if os.path.normcase(os.path.realpath(input_path)) == os.path.normcase(os.path.realpath(output)) or (
                os.path.exists(output) and os.path.samefile(input_path, output)
            ):
                raise ValueError("The output must not replace the input PDF.")
            if not overwrite and os.path.exists(output):
                raise FileExistsError(f"Output already exists: {output}")
        completed = 0
        try:
            for output, group in zip(output_paths, groups):
                self.merge([input_path], output, overwrite=overwrite, page_orders=[group])
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(groups), output)
        except Exception as exc:
            raise RuntimeError(f"Split stopped after saving {completed} of {len(groups)} files: {exc}") from exc
