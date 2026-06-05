from PIL import Image, ImageEnhance


def img_to_escpos(img, target_width, dither="floyd", threshold=128, contrast=1.0):
    img = img.convert("L")
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    width, height = img.size
    if width != target_width:
        ratio = target_width / width
        img = img.resize((target_width, int(height * ratio)), Image.Resampling.BICUBIC)

    if dither.lower() == "none":
        img = img.point(lambda p: 255 if p > threshold else 0, mode="1")
    else:
        img = img.convert("1")

    width, height = img.size
    row_bytes = (width + 7) // 8
    data = bytearray()
    data += b"\x1B@"
    data += b"\x1Dv0\x00" + bytes([row_bytes & 0xFF, row_bytes >> 8, height & 0xFF, height >> 8])

    px = img.load()
    for y in range(height):
        byte = 0
        bit = 0
        for x in range(width):
            bit_val = 0 if px[x, y] == 255 else 1
            byte = (byte << 1) | bit_val
            bit += 1
            if bit == 8:
                data.append(byte)
                byte = 0
                bit = 0
        if bit:
            data.append(byte << (8 - bit))

    data += b"\x1B\x64\x04\x1B\x69"
    return bytes(data)
