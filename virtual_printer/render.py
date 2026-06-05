from PIL import Image, ImageDraw, ImageFont


def _get_font(size=18):
    for font_name in ["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "FreeMono.ttf", "consola.ttf"]:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_preview_png(data_bytes, out_png, width_px, left_margin_px, right_margin_px):
    font_base = _get_font(18)
    img = Image.new("L", (width_px, 5000), 255)
    draw = ImageDraw.Draw(img)
    y = 12
    align = 0
    bold = 0
    underline = 0
    lh_base = font_base.getbbox("A")[3] + 4
    lh = lh_base
    codepage = "cp437"
    cuts = []
    buf = []
    i = 0
    n = len(data_bytes)

    def flush_line():
        nonlocal y, buf
        if not buf:
            return
        s = bytes(buf).decode(codepage, errors="ignore")
        if len(s) > 8000:
            s = s[:8000]
        scale = 2 if bold else 1
        font = _get_font(18 * scale)
        w = draw.textlength(s, font=font)
        available_w = max(16, width_px - left_margin_px - right_margin_px)
        x = left_margin_px
        if align == 1:
            x = left_margin_px + max(0, (available_w - w) // 2)
        elif align == 2:
            x = left_margin_px + max(0, available_w - w)
        draw.text((x, y), s, font=font, fill=0)
        if underline:
            underline_y = y + font.getbbox("A")[3]
            draw.line([(x, underline_y), (x + w, underline_y)], fill=0, width=1)
        y += lh
        buf = []

    while i < n:
        b = data_bytes[i]
        if b == 0x0A:
            flush_line()
            i += 1
            continue
        if b == 0x0D:
            i += 1
            continue
        if b == 0x1B:
            if i + 1 >= n:
                break
            cmd = data_bytes[i + 1]
            if cmd == 0x40:
                align = 0
                bold = 0
                underline = 0
                lh = lh_base
                buf = []
                i += 2
                continue
            if cmd == 0x64 and i + 2 < n:
                flush_line()
                y += data_bytes[i + 2] * lh
                i += 3
                continue
            if cmd in (0x69, 0x6D):
                flush_line()
                cuts.append(y)
                i += 2
                continue
            if cmd == 0x61 and i + 2 < n:
                align = data_bytes[i + 2]
                i += 3
                continue
            if cmd == 0x45 and i + 2 < n:
                bold = 1 if data_bytes[i + 2] else 0
                i += 3
                continue
            if cmd == 0x2D and i + 2 < n:
                underline = 1 if data_bytes[i + 2] else 0
                i += 3
                continue
            if cmd == 0x33 and i + 2 < n:
                k = data_bytes[i + 2]
                lh = max(12, k)
                i += 3
                continue
            if cmd == 0x74 and i + 2 < n:
                i += 3
                continue
            i += 2
            continue
        if b == 0x1D:
            if i + 1 >= n:
                break
            cmd = data_bytes[i + 1]
            if cmd == 0x56:
                flush_line()
                cuts.append(y)
                i += 2
                if i < n and data_bytes[i] in (0, 1, 48, 49):
                    i += 1
                continue
            if cmd == 0x76 and i + 5 < n and data_bytes[i + 2] in (0x30, 48):
                flush_line()
                xL = data_bytes[i + 4]
                xH = data_bytes[i + 5]
                yL = data_bytes[i + 6]
                yH = data_bytes[i + 7]
                i += 8
                wbytes = xL + 256 * xH
                rows = yL + 256 * yH
                total = wbytes * rows
                payload = data_bytes[i : i + total]
                i += total
                px_w = wbytes * 8
                img2 = Image.new("L", (px_w, rows), 255)
                draw2 = ImageDraw.Draw(img2)
                for yy in range(rows):
                    off = yy * wbytes
                    x = 0
                    for bb in payload[off : off + wbytes]:
                        for bit in range(7, -1, -1):
                            val = (bb >> bit) & 1
                            if val:
                                draw2.point((x, yy), fill=0)
                            x += 1
                ratio = min(1.0, width_px / float(img2.width))
                disp = img2.resize((int(img2.width * ratio), int(img2.height * ratio)))
                img.paste(disp, (left_margin_px, y))
                y += disp.height + 6
                continue
            if cmd == 0x21 and i + 2 < n:
                val = data_bytes[i + 2]
                bold = 1 if val else 0
                i += 3
                continue
            i += 2
            continue
        buf.append(b)
        i += 1

    flush_line()
    height = max(120, y + 24)
    img = img.crop((0, 0, width_px, height))
    img.save(out_png)
    return cuts


def derive_width_px_from_data(data_bytes, fallback):
    i = 0
    n = len(data_bytes)
    while i + 7 < n:
        if data_bytes[i] == 0x1D and data_bytes[i + 1] == 0x76 and data_bytes[i + 2] in (0x30, 48):
            xL = data_bytes[i + 4]
            xH = data_bytes[i + 5]
            wbytes = xL + 256 * xH
            return max(128, min(1024, wbytes * 8))
        i += 1
    return fallback


def text_line_width(line, font):
    try:
        bbox = font.getbbox(line)
        return bbox[2] - bbox[0]
    except Exception:
        return len(line) * 8
