# 出口要闻日报 · GitHub Actions 自动化

每天北京时间 08:30 自动运行（GitHub Actions 托管，不受沙箱休眠影响）：

1. 增量采集四个数据源：海关归类预裁定决定书、商务部政策发布、
   中国出口管制信息网（清单公告/目录/国内动态）、海关总署公告
2. 自动筛选出口相关条目，生成当日结构化日报
3. 渲染同款版式长图（1080px 深蓝封面信息卡）
4. 长图提交到仓库，经 jsDelivr CDN 生成国内可访问的永久直链
5. 推送到微信（Server酱 / PushPlus / 企业微信机器人任选）
6. 采集状态自动回写仓库（增量去重持久化），当日 PDF/汇总存为 Artifact

## 首次部署步骤

1. 创建 GitHub 仓库（Private 也可以），把本目录全部文件推上去
2. 仓库 Settings → Secrets and variables → Actions → New repository secret，
   添加以下**任意一个**推送通道：
   - `SERVERCHAN_KEY`：sct.ftqq.com 微信扫码登录 → 复制 SendKey（推荐，免费5条/天）
   - `PUSHPLUS_TOKEN`：pushplus.plus（需实名）
   - `WECOM_WEBHOOK`：企业微信群机器人 Webhook 地址
3. Actions 页面启用 workflow → 手动 Run workflow 测试一次
4. 成功后每天 08:30 左右自动运行（GitHub 定时可能有几分钟延迟）

## 状态持久化

`state.json` 记录已采集条目（含 2000+ 历史预裁定索引），每次运行后自动 commit
回仓库实现增量去重。**不要手动编辑它**；如需重建，删除后运行
`python harvest.py --mode init`（全量回填约 30-60 分钟）。

## 图床说明

长图经 jsDelivr（`cdn.jsdelivr.net`）分发，国内一般可直接访问；
若仓库为 Private，jsDelivr 无法读取，需把仓库设为 Public 或改用其他图床。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| harvest.py | 采集主脚本（预裁定/商务部/管制网/海关公告） |
| digest.py collect / render | 筛选出口相关条目 / 渲染长图 |
| digest_auto.py | 自动生成当日日报结构（无 AI：标题+编号+税号+原文链接） |
| push.py | 长图直链（jsDelivr / sm.ms / catbox）+ 推送微信 |
| state.json | 增量去重状态（自动回写） |
