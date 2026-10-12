"""Stand-ins for the matrix and its canvas, so frames can be drawn and inspected without hardware

The emulator's own canvas opens a display window when it is built, so it can't be used headless. Its
graphics.DrawText and Font only need width and SetPixel from a canvas, so they work against this one.
"""


class FakeCanvas:
    def __init__(self, width: int = 64, height: int = 32):
        self.width = width
        self.height = height
        self.pixels: dict[tuple[int, int], tuple[int, int, int]] = {}
        self.fills: list[tuple[int, int, int]] = []

    def Clear(self):
        self.pixels = {}

    def Fill(self, r, g, b):
        self.fills.append((r, g, b))
        self.pixels = {(x, y): (r, g, b) for x in range(self.width) for y in range(self.height)}

    def SetPixel(self, x, y, r, g, b):
        # clipped like the real canvas, so sprites driving on and off screen draw only what is visible
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[(int(x), int(y))] = (r, g, b)


class FakeMatrix:
    """Records a copy of every frame swapped onto the display"""

    def __init__(self):
        self.frames: list[dict[tuple[int, int], tuple[int, int, int]]] = []

    def SwapOnVSync(self, canvas):
        self.frames.append(dict(canvas.pixels))
        return canvas
