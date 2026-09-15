# 选品筛子

这是 `datta` 项目的日常预测和人工筛选包。

## 日常运行

模型阶段只负责打分并输出 CSV：

```powershell
cd C:\Users\ZFGJ-WCH\Desktop\datta\screener
$env:HF_HOME = "F:\Clip\hf-cache"
$env:HF_HUB_OFFLINE = "1"
$env:OMP_NUM_THREADS = "1"
F:\Clip\venv\Scripts\python.exe src\run.py --input "C:\path\日报.csv"
```

说明：

- 日报后缀可以是 `.csv`，但很多文件实际是 xlsx，代码会按当前读取逻辑处理。
- `config.json` 当前指向 `D:/temu_rank_npz`，用于读取图片/文本向量缓存。
- 当前可部署模型在 `model/lgbm_full.txt`。
- `src/run.py` 不再生成 HTML，避免模型阶段和前端展示耦合。
- `src/run.py` 会先看图片向量缓存，只下载当前日报里未缓存图片向量的主图。

## HTML pipeline

HTML 阶段读取模型输出的 `*_scored.csv`：

```powershell
F:\Clip\venv\Scripts\python.exe src\generate_html.py --input output\913_scored.csv
```

也可以从项目根目录使用包装脚本：

```powershell
C:\Users\ZFGJ-WCH\Desktop\datta\pipeline\generate_html_from_scored.ps1 -InputCsv C:\Users\ZFGJ-WCH\Desktop\datta\screener\output\913_scored.csv
```

这个阶段会统一生成完整筛子、人工筛选页、自动过滤后的 Top CSV。

## 输出文件

预测完成后看 `output/`：

```text
*_scored.csv       # 全量打分
*_screener.html    # HTML 阶段生成，自己看的完整筛子
*_分享.html        # HTML 阶段生成，先给自己人工筛，筛完后再保存发送
*_Top5pct_去违禁_去2D平面.csv
```

## 分享页人工筛选

`*_分享.html` 当前规则：

- 默认只展示模型 Top 5%。
- 自动剔除违禁词命中商品。
- 自动剔除 `2D / 二维 / 平面 / flat printing / frameless / 无框` 等平面印刷类商品。
- 页面支持价格筛选、标题关键词筛选、分类筛选。
- 每张卡片支持 `打开 / 删除 / 保留`。
- 删除/保留状态会写入浏览器本地存储，按 F5 刷新后仍会保留。
- 点 `全部保留` 会清空当前页面保存的删除状态。
- 点 `保存筛选后HTML` 会另存一个只包含当前可见且未删除商品的 HTML。
- 另存后的人工筛选版 HTML 仍支持价格、关键词、分类筛选，但没有删除/保留按钮。

## 913 当前结果

```text
output/913_分享.html
output/913_Top5pct_去违禁_去2D平面.csv
```

913 Top500 自动过滤后保留 203 条；过滤后违禁命中 0，2D/平面命中 0。

## 914 当前结果

```text
output/914_scored.csv
output/914_分享.html
output/914_Top5pct_去违禁_去2D平面.csv
```

914 使用 909-913 增量训练模型预测；Top500 自动过滤后保留 262 条，过滤后违禁命中 0，2D/平面命中 0。
