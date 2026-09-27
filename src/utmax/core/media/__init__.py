"""A pure-Python MP4/MOV muxer: fragmented YouTube streams plus subtitles into one file.

``fmp4`` indexes fragmented inputs, ``tx3g`` turns transcripts into subtitle tracks,
``tables`` and ``moov`` write the sample tables and track boxes, ``mux`` plans the output as a
list of byte copies and literal blobs, and ``progressive`` reads finished files back (used to
verify the output). Nothing here performs I/O: inputs are read through ``ByteSource``.
"""
