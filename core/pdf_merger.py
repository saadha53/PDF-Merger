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
    ) -> None:
        """
        Merge PDFs using pypdf.PdfWriter.
        progress_callback(current_index, total_count, filename)
        """
        paths = list(input_paths)
        if not paths:
            raise ValueError("Add at least one PDF before merging.")
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
                    writer.append(reader)
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
