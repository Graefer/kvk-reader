"""Generate a smartcard chip icon for the KVK-Reader app.

Creates a 256x256 PNG with a gold smartcard chip design,
then converts to .ico with multiple sizes.
"""

from PIL import Image, ImageDraw

SIZE = 256
PAD = 20  # outer padding


def draw_chip_icon():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Card body (rounded rectangle, light blue-gray)
    card_color = (220, 230, 240, 255)
    card_border = (160, 175, 195, 255)
    draw.rounded_rectangle(
        [PAD, PAD, SIZE - PAD, SIZE - PAD],
        radius=20,
        fill=card_color,
        outline=card_border,
        width=3,
    )

    # Chip body (gold rectangle, slightly rounded)
    chip_x0 = 55
    chip_y0 = 65
    chip_x1 = 200
    chip_y1 = 190
    chip_gold = (218, 185, 100, 255)
    chip_border = (180, 150, 70, 255)

    draw.rounded_rectangle(
        [chip_x0, chip_y0, chip_x1, chip_y1],
        radius=12,
        fill=chip_gold,
        outline=chip_border,
        width=2,
    )

    # Contact pads — the characteristic pattern of a smart card chip
    # The chip has a center divider and pads on left and right
    pad_color = (195, 160, 60, 255)
    pad_line = (170, 140, 50, 255)
    cx = (chip_x0 + chip_x1) // 2  # center x = 127

    # Vertical center divider
    draw.rectangle([cx - 2, chip_y0 + 10, cx + 2, chip_y1 - 10], fill=pad_line)

    # Horizontal center divider
    cy = (chip_y0 + chip_y1) // 2
    draw.rectangle([chip_x0 + 10, cy - 2, chip_x1 - 10, cy + 2], fill=pad_line)

    # Left pads (3 rows, 1 column)
    lpad_x0 = chip_x0 + 12
    lpad_x1 = cx - 8
    pad_h = 28
    gap = 8

    # Top-left pad
    y = chip_y0 + 14
    draw.rounded_rectangle([lpad_x0, y, lpad_x1, y + pad_h], radius=4, fill=pad_color, outline=pad_line, width=1)

    # Middle-left pad
    y = cy - pad_h // 2
    draw.rounded_rectangle([lpad_x0, y, lpad_x1, y + pad_h], radius=4, fill=pad_color, outline=pad_line, width=1)

    # Bottom-left pad
    y = chip_y1 - 14 - pad_h
    draw.rounded_rectangle([lpad_x0, y, lpad_x1, y + pad_h], radius=4, fill=pad_color, outline=pad_line, width=1)

    # Right pads (3 rows)
    rpad_x0 = cx + 8
    rpad_x1 = chip_x1 - 12

    # Top-right pad
    y = chip_y0 + 14
    draw.rounded_rectangle([rpad_x0, y, rpad_x1, y + pad_h], radius=4, fill=pad_color, outline=pad_line, width=1)

    # Middle-right pad (wider — the main contact)
    y = cy - pad_h // 2
    draw.rounded_rectangle([rpad_x0, y, rpad_x1, y + pad_h], radius=4, fill=pad_color, outline=pad_line, width=1)

    # Bottom-right pad
    y = chip_y1 - 14 - pad_h
    draw.rounded_rectangle([rpad_x0, y, rpad_x1, y + pad_h], radius=4, fill=pad_color, outline=pad_line, width=1)

    return img


def main():
    import os

    base_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
    os.makedirs(base_dir, exist_ok=True)

    img = draw_chip_icon()

    # Save PNG
    png_path = os.path.join(base_dir, "app_icon.png")
    img.save(png_path, "PNG")
    print(f"Saved: {png_path}")

    # Save ICO with multiple sizes
    ico_path = os.path.join(base_dir, "app_icon.ico")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_images = []
    for s in sizes:
        resized = img.resize(s, Image.LANCZOS)
        ico_images.append(resized)

    ico_images[0].save(
        ico_path, format="ICO",
        sizes=sizes,
        append_images=ico_images[1:],
    )
    print(f"Saved: {ico_path}")


if __name__ == "__main__":
    main()
