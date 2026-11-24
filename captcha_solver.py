"""Offline OCR for one login challenge; never upload images or log answers."""
import re
from renewal_core import StopRenewal, report


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
    report('阶段：已识别验证码图片和输入框，进行离线 OCR。')
    ocr = ddddocr.DdddOcr(show_ad=False)
    result = ocr.classification(image_bytes)
    try:
        answer = arithmetic_answer(result)
    except StopRenewal:
        ocr.set_ranges('0123456789+-x/=')
        probabilities = ocr.classification(image_bytes, probability=True)
        constrained = ''.join(probabilities['charsets'][max(range(len(row)), key=row.__getitem__)]
                              for row in probabilities['probability'])
        answer = arithmetic_answer(constrained)
    button = page.locator('input[type="submit"]:visible').or_(page.get_by_role('button', name='Login', exact=True))
    if button.count() != 1:
        raise StopRenewal('无法唯一识别验证码提交按钮；未提交。')
    field.fill(answer)
    report('阶段：提交一次图形验证码答案。')
    button.click()
