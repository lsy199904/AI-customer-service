"""浏览器端浮窗 UI 回归（playwright chromium）；浏览器不可用时自动跳过。

迁移自 tests/test_widget_ui.js：同一套 mock 路由与断言，改跑在 pytest 入口下。
环境变量：UI_SCREENSHOT / V2_SCREENSHOT 保存过程截图；CHROME_PATH 指定浏览器可执行文件。
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

pytest.importorskip('playwright', reason='playwright 未安装：uv sync 后执行 uv run playwright install chromium')
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WIDGET_JS = (ROOT / 'app/static/widget.js').read_text(encoding='utf-8')
MEDIA_FILES = {'/media/hub-03.png', '/media/business-verification.png'}
GUIDE_STAGES = ['完善企业资料', '选择认证方式', '办理认证与审核', '查看认证结果']

PAGE_HTML = ('<!doctype html><html lang="zh"><head><meta charset="utf-8"></head>'
             '<body style="background:#eef3fb"><script src="/widget.js"></script></body></html>')
BOOTSTRAP = {'welcome': '您好，我是 SmartTITU 智能客服。', 'link_policy': {'hosts': ['www.smarttitu.cn']},
             'quick_questions': ['注册流程', '企业认证流程', '服务订购流程', '客户充值流程', '账单支付流程', '在线开票流程'],
             'capabilities': {'streaming': False}}
SOURCE_KB_TEST = {'id': 'KB-test', 'title': '问题44 操作审计', 'content': '审计说明', 'source_file': '用户手册.docx'}
DEFAULT_ANSWER = ('1. 您可以在操作审计页面查看平台操作记录。\n2. 官网：https://www.smarttitu.cn\n\n'
                  '图片展示：\n![套餐版本介绍](https://widget.test/media/hub-03.png)\n'
                  '更多详情请参考手册：\nhttps://raw.githubusercontent.com/lsy199904/AI-customer-service/main/docs/sources/manual.pdf')
DEFAULT_IMAGES = [{'id': 'plan', 'title': '套餐版本介绍', 'url': '/media/hub-03.png'},
                  {'id': 'plan-duplicate', 'title': '套餐版本介绍', 'url': '/media/hub-03.png'}]

# 流式用例：接管 fetch，bootstrap 强制 capabilities.streaming=true，
# /messages/stream 返回手工控制的 SSE 流，window.finishStream() 推送剩余分片。
STREAMING_SETUP = """
() => {
  const original = window.fetch; window.restoreFetch = () => { window.fetch = original; };
  window.fetch = async (url, options) => {
    if (String(url).endsWith('/v1/bootstrap')) {
      const response = await original(url, options), body = await response.json();
      body.capabilities.streaming = true; return new Response(JSON.stringify(body));
    }
    if (String(url).endsWith('/messages/stream')) {
      const encoder = new TextEncoder(), request = JSON.parse(options.body);
      return new Response(new ReadableStream({start(controller) {
        const emit = (kind, data) => controller.enqueue(encoder.encode('event: ' + kind + '\\n' + 'data: ' + JSON.stringify(data) + '\\n\\n'));
        emit('status', {stage: 'generating'}); emit('delta', {text: '第一段文字'});
        window.finishStream = () => {
          emit('delta', {text: '，第二段文字。'});
          emit('complete', {answer: '第一段文字，第二段文字。', status: 'answered', request_id: request.request_id,
                            images: [{id: 'plan', title: '套餐版本介绍', url: '/media/hub-03.png'}],
                            citations: [{id: 'KB-test', title: '操作审计'}]});
          controller.close();
        };
      }}), {headers: {'Content-Type': 'text/event-stream'}});
    }
    return original(url, options);
  };
}
"""


def message_reply(body):
    """与原 JS mock 一致：默认回答基础上按提问内容覆盖分支字段。"""
    message = body['message']
    if message == '，':
        return {'answer': '请问您想了解 SmartTITU 的哪项功能，或遇到了什么问题？',
                'status': 'answered', 'reason': 'unclear_input', 'request_id': body['request_id']}
    if message == '测试失败':
        return {'answer': '暂时无法完成回答，请稍后重试。', 'status': 'suggestions',
                'request_id': body['request_id'], 'suggestions': ['操作审计']}
    data = {'answer': DEFAULT_ANSWER, 'status': 'answered', 'request_id': body['request_id'],
            'images': DEFAULT_IMAGES, 'citations': [{'id': 'KB-test', 'title': '问题44 操作审计'}]}
    if message == '转人工客服':
        data['handoff'] = True
        data['contact'] = {'phone': '4008841883', 'email': 'help@china-entercom.net'}
    elif message == '企业认证流程':
        data['answer'] = '登录后完善企业资料，选择在线或线下认证，并根据页面提示办理。'
        data['images'] = []
        data['actions'] = [{'type': 'guide', 'label': '带我一步步办理', 'message': '分步指导：企业认证流程'}]
    elif message == '支付不了':
        data.update({'answer': '您遇到的是账单支付，还是充值支付的问题？', 'images': [], 'citations': [], 'intent': 'clarification',
                     'actions': [{'type': 'clarify', 'label': '账单支付流程', 'message': '账单支付流程'},
                                 {'type': 'clarify', 'label': '客户充值流程', 'message': '客户充值流程'}]})
    elif message in ('分步指导：企业认证流程', '这一步已完成', '返回上一步', '结束指导'):
        guide_step = 1 if message == '这一步已完成' else 0
        ended = message == '结束指导'
        data['answer'] = ('已结束这段分步指导。' if ended else
                          ('进入企业认证页面，选择在线认证或线下认证。' if guide_step else
                           '登录后完善企业名称、行业和公司地址等资料，按页面提示提交。'))
        data['guidance'] = {'flow_id': 'verification', 'title': '企业认证流程', 'step': guide_step,
                            'total': 4, 'stages': GUIDE_STAGES, 'status': 'ended' if ended else 'active'}
        data['images'] = [{'id': 'business-verification', 'title': '企业认证流程', 'url': '/media/business-verification.png'}]
        data['citations'] = [{'id': 'KB-test', 'title': '问题6 企业认证流程'}]
        data['actions'] = [] if ended else [
            {'type': 'guide', 'label': '这一步已完成', 'message': '这一步已完成'},
            {'type': 'guide', 'label': '这一步怎么做', 'message': '这一步怎么做'},
            *([{'type': 'guide', 'label': '返回上一步', 'message': '返回上一步'}] if guide_step else []),
            {'type': 'guide', 'label': '结束指导', 'message': '结束指导'}]
    elif message == '只显示图片':
        data['answer'] = '图片展示：\n![套餐版本介绍](https://widget.test/media/hub-03.png)'
    return data


def install_mock_routes(page):
    """拦截 widget.test 全部请求：静态资源读仓库文件，API 走 mock；返回请求捕获列表。"""
    seen_requests = []

    def handle(route):
        request = route.request
        path = urlparse(request.url).path
        if path.startswith('/smart-bot/'):
            path = path[len('/smart-bot'):]
        if path == '/':
            route.fulfill(content_type='text/html', body=PAGE_HTML)
        elif path == '/widget.js':
            route.fulfill(content_type='text/javascript', body=WIDGET_JS)
        elif path in MEDIA_FILES:
            route.fulfill(content_type='image/png', body=(ROOT / 'app/static' / path.lstrip('/')).read_bytes())
        elif path == '/v1/bootstrap':
            route.fulfill(content_type='application/json', body=json.dumps(BOOTSTRAP, ensure_ascii=False))
        elif path == '/v1/sessions' and request.method == 'GET':
            route.fulfill(content_type='application/json', body='{"items":[]}')
        elif path == '/v1/sessions':
            route.fulfill(content_type='application/json', body='{"session_id":"preview-session"}')
        elif path.endswith('/messages'):
            seen_requests.append({'headers': request.headers, 'body': request.post_data_json})
            route.fulfill(content_type='application/json',
                          body=json.dumps(message_reply(request.post_data_json), ensure_ascii=False))
        elif path == '/v1/sources/KB-test':
            route.fulfill(content_type='application/json', body=json.dumps(SOURCE_KB_TEST, ensure_ascii=False))
        else:
            route.fulfill(status=404, body='')

    page.route('https://widget.test/**', handle)
    return seen_requests


@pytest.fixture(scope='module')
def browser():
    playwright = sync_playwright().start()
    try:
        executable = os.environ.get('CHROME_PATH')
        browser = playwright.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))
    except Exception as error:  # 浏览器二进制缺失等环境问题：跳过而非失败
        playwright.stop()
        pytest.skip(f'playwright chromium 不可用，先执行 uv run playwright install chromium（{error}）')
    yield browser
    browser.close()
    playwright.stop()


@pytest.fixture()
def ui(browser):
    page = browser.new_page(viewport={'width': 1100, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    requests = install_mock_routes(page)
    page.goto('https://widget.test/')
    page.evaluate("() => window.SmartTITUAssistant.configure({getToken: async () => 'preview-only'})")
    yield SimpleNamespace(page=page, errors=errors, requests=requests)
    page.close()


def ask(ui, message):
    ui.page.evaluate('message => window.SmartTITUAssistant.ask(message)', message)


def assert_no_page_errors(ui):
    assert not ui.errors, f'页面出现未捕获异常：{ui.errors}'


@pytest.mark.ui
def test_reply_rendering_headers_and_layout(ui):
    page = ui.page
    ask(ui, '操作审计')
    original = page.locator('#smarttitu-panel').bounding_box()
    page.get_by_role('button', name='放大窗口', exact=True).click()
    assert page.locator('#smarttitu-panel').bounding_box()['width'] > original['width']
    page.get_by_role('button', name='还原窗口', exact=True).click()
    assert page.locator('#smarttitu-panel').bounding_box()['width'] == original['width']
    assert page.locator('.message.user .message-avatar svg').count() == 1
    assert page.locator('.message.user .message-role').inner_text() == '您'
    assert page.locator('.message.assistant .message-avatar svg').count() == 2
    assert page.get_by_role('button', name='用户手册：操作审计', exact=True).count() == 1
    assert page.locator('.bubble a').get_attribute('target') == '_blank'
    assert page.locator('.reply-images .image-button').count() == 1
    page.locator('.image-button img').evaluate('img => img.decode()')
    assert page.locator('.image-button img').evaluate('img => img.naturalWidth > 0')
    assert page.locator('.bubble img').count() == 0
    reply = page.locator('.message.assistant .bubble').last.inner_text()
    assert '图片展示' not in reply and '更多详情' not in reply and 'raw.githubusercontent.com' not in reply
    assert ui.requests[0]['headers']['x-request-id'] == ui.requests[0]['body']['request_id']
    assert ui.requests[0]['headers']['x-widget-id'].startswith('window-')
    assert page.locator('.composer .quick button').count() == 6
    assert page.locator('.media-card .original-link').count() == 1
    assert page.locator('.media-footer .image-caption').inner_text() == '套餐版本介绍'
    screenshot = os.environ.get('UI_SCREENSHOT')
    if screenshot:
        page.get_by_role('button', name='用户手册：操作审计', exact=True).scroll_into_view_if_needed()
        page.locator('#smarttitu-panel').screenshot(path=screenshot)
        page.get_by_role('button', name='放大窗口', exact=True).click()
        page.locator('#smarttitu-panel').screenshot(path=screenshot.removesuffix('.png') + '-放大.png')
        page.get_by_role('button', name='还原窗口', exact=True).click()
    page.get_by_role('button', name='用户手册：操作审计', exact=True).click()
    assert page.locator('.source-content h3').inner_text() == '用户手册：操作审计'
    page.get_by_role('button', name='← 返回对话').click()
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_images_only_reply_has_no_bubble(ui):
    ask(ui, '只显示图片')
    assert ui.page.locator('.message.assistant').last.locator('.bubble').count() == 0
    assert ui.page.locator('.message.assistant').last.locator('.image-button').count() == 1
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_failure_feedback_shows_request_id(ui):
    ask(ui, '测试失败')
    ui.page.get_by_text('反馈问题', exact=True).click()
    assert ui.page.get_by_role('button', name='复制问题编号', exact=True).count() == 1
    assert ui.requests[-1]['body']['request_id'] in ui.page.locator('details').inner_text()
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_mobile_viewport_and_reduced_motion(ui):
    page = ui.page
    ask(ui, '操作审计')
    page.set_viewport_size({'width': 375, 'height': 812})
    assert page.locator('#smarttitu-panel').evaluate('el => el.getBoundingClientRect().width <= window.innerWidth')
    page.get_by_role('button', name='放大窗口', exact=True).click()
    assert page.locator('#smarttitu-panel').evaluate(
        'el => {const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.bottom <= innerHeight;}')
    screenshot = os.environ.get('UI_SCREENSHOT')
    if screenshot:
        page.locator('#smarttitu-panel').screenshot(path=screenshot.removesuffix('.png') + '-手机.png')
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.message').last.evaluate('el => getComputedStyle(el).animationName') == 'none'
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_streaming_reply(ui):
    page = ui.page
    page.evaluate(STREAMING_SETUP)
    page.evaluate("() => { window.pendingStream = window.SmartTITUAssistant.ask('真正流式测试'); }")
    page.locator('.message.streaming .bubble').wait_for()
    assert page.locator('.message.streaming .bubble').inner_text() == '第一段文字'
    assert page.locator('.message.streaming .image-button').count() == 0
    page.evaluate('async () => { window.finishStream(); await window.pendingStream; }')
    assert page.locator('.message.streaming').count() == 0
    assert page.locator('.message.assistant .bubble').last.inner_text() == '第一段文字，第二段文字。'
    assert page.locator('.message.assistant').last.locator('.image-button').count() == 1
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_guided_flow_navigation(ui):
    page = ui.page
    ask(ui, '企业认证流程')
    page.locator('.message.assistant').last.get_by_role('button', name='带我一步步办理', exact=True).click()
    page.locator('.guidance-card').wait_for()
    assert page.locator('.guidance-card [aria-current="step"]').inner_text() == '1\n完善企业资料'
    page.locator('.message.assistant').last.get_by_role('button', name='这一步已完成', exact=True).click()
    page.locator('.guidance-card').last.get_by_text('选择认证方式', exact=True).wait_for()
    page.wait_for_function(
        "document.querySelector('#smarttitu-assistant-widget').shadowRoot.querySelectorAll('.guidance-card').length === 2")
    assert '选择认证方式' in page.locator('.guidance-card [aria-current="step"]').last.inner_text()
    expect(page.get_by_role('button', name='这一步已完成', exact=True).first).to_be_disabled()
    screenshot = os.environ.get('V2_SCREENSHOT')
    if screenshot:
        page.set_viewport_size({'width': 1100, 'height': 1000})
        page.locator('.guidance-card').last.scroll_into_view_if_needed()
        page.locator('#smarttitu-panel').screenshot(path=screenshot)
    page.locator('.message.assistant').last.get_by_role('button', name='返回上一步', exact=True).click()
    page.wait_for_function(
        "document.querySelector('#smarttitu-assistant-widget').shadowRoot.querySelectorAll('.guidance-card').length === 3")
    assert '完善企业资料' in page.locator('.guidance-card [aria-current="step"]').last.inner_text()
    page.locator('.message.assistant').last.get_by_role('button', name='结束指导', exact=True).click()
    page.locator('.guidance-badge').last.get_by_text('已结束', exact=True).wait_for()
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_clarification_offers_both_paths(ui):
    ask(ui, '支付不了')
    assert ui.page.locator('.message.assistant').last.locator('.assistant-actions button').count() == 2
    assert_no_page_errors(ui)


@pytest.mark.ui
def test_handoff_copies_contacts_without_links(ui):
    page = ui.page
    page.evaluate("() => { window.copiedContacts = []; Object.defineProperty(navigator, 'clipboard', "
                  "{configurable: true, value: {writeText: async value => window.copiedContacts.push(value)}}); }")
    page.get_by_role('button', name='打开智能客服').click()
    page.get_by_text(BOOTSTRAP['welcome'], exact=True).wait_for()
    page.get_by_role('button', name='联系人工', exact=True).click()
    page.get_by_role('button', name='复制电话', exact=True).click()
    assert ui.requests[-1]['body']['client_action'] == 'handoff'
    page.get_by_role('button', name='复制邮箱', exact=True).click()
    assert page.evaluate('() => window.copiedContacts') == ['4008841883', 'help@china-entercom.net']
    assert page.locator('.contact a').count() == 0
    assert page.get_by_role('button', name='复制电话', exact=True).inner_text() == '已复制'
    assert_no_page_errors(ui)

@pytest.mark.ui
def test_punctuation_only_can_be_sent_and_gets_a_neutral_prompt(ui):
    page=ui.page
    ask(ui,'操作审计')
    initial_count=len(ui.requests)
    user_messages=page.locator('.message.user').count()
    page.get_by_role('textbox',name='客服问题').fill('，')
    page.get_by_role('button',name='发送',exact=True).click()
    expect(page.get_by_text('请问您想了解 SmartTITU 的哪项功能，或遇到了什么问题？',exact=True)).to_be_visible()
    assert len(ui.requests)==initial_count+1
    assert ui.requests[-1]['body']['message']=='，'
    assert page.locator('.message.user').count()==user_messages+1
    assert_no_page_errors(ui)
