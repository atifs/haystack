import logging
import mimetypes
from collections import defaultdict
from pathlib import Path
from typing import List, Union, Optional, Dict

from haystack import component
from haystack.dataclasses import ByteStream

logger = logging.getLogger(__name__)


@component
class FileTypeRouter:
    """
    FileTypeRouter takes a list of data sources (file paths or byte streams) and groups them by their corresponding
    MIME types.

    For file paths, MIME types are inferred from their extensions, while for byte streams, MIME types
    are determined from the provided metadata.

    The set of MIME types to consider is specified during the initialization of the component.

    This component is useful when you need to classify a large collection of files or data streams according to their
    MIME types and route them to different components for further processing.

    Usage example:
    ```python
    from haystack.components.routers import FileTypeRouter

    router = FileTypeRouter(mime_types=["text/plain"])

    print(router.run(sources=["text_file.txt", "pdf_file.pdf"]))

    # defaultdict(<class 'list'>, {'text/plain': [PosixPath('text_file.txt')],
    #                              'unclassified': [PosixPath('pdf_file.pdf')]})
    ```
    """

    def __init__(self, mime_types: List[str]):
        """
        :param mime_types: A list of file mime types to consider when routing files
            (e.g. `["text/plain", "audio/x-wav", "image/jpeg"]`).
        """
        if not mime_types:
            raise ValueError("The list of mime types cannot be empty.")

        for mime_type in mime_types:
            if not self._is_valid_mime_type_format(mime_type):
                raise ValueError(
                    f"Unknown mime type: '{mime_type}'. Ensure you passed a list of strings in the 'mime_types' parameter"
                )

        component.set_output_types(self, unclassified=List[Path], **{mime_type: List[Path] for mime_type in mime_types})
        self.mime_types = mime_types

    def run(self, sources: List[Union[str, Path, ByteStream]]) -> Dict[str, List[Union[ByteStream, Path]]]:
        """
        Categorizes the provided data sources by their MIME types.

        :param sources: A list of file paths or byte streams to categorize.

        :returns: A dictionary where the keys are MIME types (or `"unclassified"`) and the values are lists of data sources.
        """

        mime_types = defaultdict(list)
        for source in sources:
            if isinstance(source, str):
                source = Path(source)

            if isinstance(source, Path):
                mime_type = self._get_mime_type(source)
            elif isinstance(source, ByteStream):
                mime_type = source.meta.get("content_type")
            else:
                raise ValueError(f"Unsupported data source type: {type(source)}")

            if mime_type in self.mime_types:
                mime_types[mime_type].append(source)
            else:
                mime_types["unclassified"].append(source)

        return mime_types

    def _get_mime_type(self, path: Path) -> Optional[str]:
        """
        Get the MIME type of the provided file path.

        :param path: The file path to get the MIME type for.

        :returns: The MIME type of the provided file path, or `None` if the MIME type cannot be determined.
        """
        extension = path.suffix.lower()
        mime_type = mimetypes.guess_type(path.as_posix())[0]
        # lookup custom mappings if the mime type is not found
        return self._get_custom_mime_mappings().get(extension, mime_type)

    def _is_valid_mime_type_format(self, mime_type: str) -> bool:
        """
        Check if the provided MIME type is in valid format

        :param mime_type: The MIME type to check.

        :returns: `True` if the provided MIME type is a valid MIME type format, `False` otherwise.
        """
        return mime_type in mimetypes.types_map.values() or mime_type in self._get_custom_mime_mappings().values()

    @staticmethod
    def _get_custom_mime_mappings() -> Dict[str, str]:
        """
        Returns a dictionary of custom file extension to MIME type mappings.
        """
        # we add markdown because it is not added by the mimetypes module
        # see https://github.com/python/cpython/pull/17995
        return {".md": "text/markdown", ".markdown": "text/markdown"}
