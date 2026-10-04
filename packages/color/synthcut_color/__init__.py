"""Colour pipeline (spec §11): source → input transform → working space →
exposure / white balance → creative grade → Rec.709 output, evaluated with
NumPy and baked into one 3D LUT per clip for FFmpeg."""
