"""Offline OCR for one login challenge; never upload images or log answers."""
import re
import os
import io
from pathlib import Path
from renewal_core import StopRenewal, report


def captcha_answer(text):
    value = text.strip()
    if re.fullmatch(r'[A-Za-z0-9]{6}', value):
        return value
    return arithmetic_answer(value)


def arithmetic_answer(text):
    value = re.sub(r'\s+', '', text).replace('×', '*').replace('x', '*').replace('X', '*').replace('÷', '/')
    match = re.fullmatch(r'(\d{1,3})([+*/-])(\d{1,3})(?:=\??)?', value)
    if not match:
        raise StopRenewal('OCR 未识别出完整的简单算式；未提交验证码。')
    left, op, right = int(match[1]), match[2], int(match[3])
    if op == '+':
        result = left + right
    elif op == '-':
        result = left - right
    elif op == '*':
        result = left * right
    elif right and left % right == 0:
        result = left // right
    else:
        raise StopRenewal('OCR 算式除法结果不确定；未提交验证码。')
    return str(result)


def solve_login_captcha(page):
    import ddddocr
    image = page.locator('img[src*="securimage_show.php"]:visible')
    field = page.locator('input[name="captcha_code"]:visible')
    if image.count() != 1 or field.count() != 1:
        raise StopRenewal('验证码图片或 captcha_code 输入框结构不匹配；未提交。')
    # Screenshot only this image. Fetching its URL again could generate a different challenge.
    image_bytes = image.screenshot()
    if os.environ.get('CAPTCHA_DIAGNOSTIC') == 'true':
        Path('captcha-diagnostic.png').write_bytes(image_bytes)
        raise StopRenewal('已保存验证码局部诊断图片；此次不识别、不提交验证码。')
    report('阶段：已识别验证码图片和输入框，进行离线 OCR。')
    from PIL import Image, ImageFilter
    source = Image.open(io.BytesIO(image_bytes)).convert('L')
    binary = source.point(lambda pixel: 0 if pixel < 225 else 255)
    cleaned = binary.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    stream = io.BytesIO()
    cleaned.save(stream, format='PNG')
    candidates = set()
    for beta in (False, True):
        ocr = ddddocr.DdddOcr(show_ad=False, beta=beta)
        for data in (image_bytes, stream.getvalue()):
            result = ocr.classification(data)
            try:
                candidates.add(captcha_answer(result))
            except StopRenewal:
                pass
    if len(candidates) != 1:
        raise StopRenewal('字符验证码 OCR 未得到唯一有效答案（含去噪及双模型尝试）；未提交。')
    answer = candidates.pop()
    button = page.locator('input[type="submit"]:visible').or_(page.get_by_role('button', name='Login', exact=True))
    if button.count() != 1:
        raise StopRenewal('无法唯一识别验证码提交按钮；未提交。')
    field.fill(answer)
    report('阶段：提交一次图形验证码答案。')
    button.click()
