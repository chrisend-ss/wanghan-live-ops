# B站云端处理失败

- BVID: \`BV1xNas6ZEpB\`
- URL: https://www.bilibili.com/video/BV1xNas6ZEpB/?spm_id_from=333.337.search-card.all.click
- 错误类型: \`HTTPError\`
- 错误: 412 Client Error: Precondition Failed for url: https://api.bilibili.com/x/web-interface/view?bvid=BV1xNas6ZEpB

## Traceback

\`\`\`text
Traceback (most recent call last):
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/tools/cloud_bilibili_review.py", line 66, in main
    result = import_bilibili(
             ^^^^^^^^^^^^^^^^
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/app/bilibili.py", line 170, in import_bilibili
    info = get_video_info(url)
           ^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/app/bilibili.py", line 46, in get_video_info
    payload = _get_json(
              ^^^^^^^^^^
  File "/home/runner/work/wanghan-live-ops/wanghan-live-ops/app/bilibili.py", line 37, in _get_json
    resp.raise_for_status()
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/requests/models.py", line 1026, in raise_for_status
    raise HTTPError(http_error_msg, response=self)
requests.exceptions.HTTPError: 412 Client Error: Precondition Failed for url: https://api.bilibili.com/x/web-interface/view?bvid=BV1xNas6ZEpB

\`\`\`
