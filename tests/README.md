# 测试

## 接口回归

```bash
python -m pytest -q          # 19 条，使用临时数据库，不碰 vagent.db
```

覆盖：启动/项目/子项目/资产（含范围与迁移）/镜头/素材/对话/设置（掩码与重置）/
上传/导出/错误出口/重启持久化。

## 浏览器交互冒烟

需要先起服务，再起一个带调试端口的 Chrome：

```bash
python vagent_app.py --port 8001
chrome --headless=new --remote-debugging-port=9222 --no-sandbox \
       --user-data-dir=/tmp/vagent-cdp http://127.0.0.1:8001/
BASE_URL=http://127.0.0.1:8001 node tests/ui_smoke.mjs
```

脚本会自建「UI 基线」项目，不依赖已有数据；41 条断言覆盖五视图渲染、
新建项目/资产/镜头、防抖保存、文字剪辑、拆分、生成、抽屉、切换器、
对话追问与继续生成、迁移、归档恢复、旁白与导出。
