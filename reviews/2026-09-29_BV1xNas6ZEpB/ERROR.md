# B站云端处理失败

- BVID: \`BV1xNas6ZEpB\`
- URL: https://www.bilibili.com/video/BV1xNas6ZEpB/?spm_id_from=333.337.search-card.all.click
- 错误类型: \`RuntimeError\`
- 错误: HTTP page fallback failed: HTTPError: 412 Client Error: Precondition Failed for url: https://www.bilibili.com/video/BV1xNas6ZEpB/?spm_id_from=333.337.search-card.all.click | Browser fallback failed: Error: Page.evaluate: Execution context was destroyed, most likely because of a navigation

## Traceback

\`\`\`text
Traceback (most recent call last):
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/tools/cloud_bilibili_review.py", line 72, in main
    result = transcribe_page_media(
             ^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/app/bilibili_browser.py", line 297, in transcribe_page_media
    media = get_page_media(url)
            ^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/app/bilibili_browser.py", line 229, in get_page_media
    raise RuntimeError(" | ".join(errors))
RuntimeError: HTTP page fallback failed: HTTPError: 412 Client Error: Precondition Failed for url: https://www.bilibili.com/video/BV1xNas6ZEpB/?spm_id_from=333.337.search-card.all.click | Browser fallback failed: Error: Page.evaluate: Execution context was destroyed, most likely because of a navigation

\`\`\`
