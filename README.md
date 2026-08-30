# SmartFJSP —— 基于智能优化算法的柔性作业车间调度系统

面向制造「生产管理」场景的 FJSP（柔性作业车间调度）智能应用。以遗传算法（GA）、
模拟退火（SA）、粒子群优化（PSO）及混合算法（GA+SA）为核心求解引擎，提供算例管理、
参数配置、优化求解、甘特图可视化、方案对比、插单重调度与结果导出，采用 B/S 架构。

> 项目代号：SmartFJSP ｜ 课程：AI 编程方法与实践（Vibe Coding）

## 技术方向映射表

| 技术方向 | 课程章节 | 在本系统中的实际作用 |
|---------|---------|-------------------|
| 遗传算法（GA） | 进化计算 | 双层编码 + POX 交叉 + 锦标赛选择，全局搜索排程方案 |
| 模拟退火（SA） | 智能优化 | Metropolis 接受准则 + 邻域搜索，作为局部搜索与混合算法组件 |
| 粒子群优化（PSO） | 智能优化 | 基于交换序列的离散 PSO，对比算法收敛与解质量 |

## 目录结构

```
SmartFJSP/
├── README.md              # 本文件（项目总说明 + 数据来源 + 预处理）
├── data/
│   ├── preprocess.py      # 预处理程序（解析 + 校验 + 统一 JSON 输出）
│   ├── raw/               # 原始算例（已下载，52 个）
│   │   ├── brandimarte/   # Mk01.fjs … Mk10.fjs（10 个 FJSP）
│   │   └── jsp/           # ft06.fjs ft10.fjs la01.fjs … la40.fjs（42 个）
│   └── processed/         # 预处理产物（52 个 JSON + index.json）
└── prompt/
    └── stage-1-*.jsonl    # 各阶段 AI 交流日志
```

> 算法模块、后端（FastAPI）、前端（Streamlit）、测试等将在后续阶段补齐。

## 数据来源

本系统使用**公开标准调度算例**（benchmark），均为学界长期使用、可自由获取与复现的
经典数据集，单个算例为几 KB 的文本文件（合计 < 100 KB），故直接纳入仓库，无需自建
大数据集。

数据来自 **IDSIA Monaldo 官方 FJSP benchmark 数据集**（该领域事实标准），经国内镜像
[GitCode「柔性作业车间调度算例汇总」](https://gitcode.com/open-source-toolkit/77780)
下载（`FJSP算例.zip`，MIT 协议）。

| 系列 | 内容 | 本系统用途 |
|------|------|-----------|
| **Brandimarte**（`Mk01–Mk10.fjs`） | FJSP 标准算例（10×6 到 20×15） | **核心测试集** |
| **Hurink `sdata`**（`mt06`/`mt10`/`la01–la40`） | 经典 JSP 的 FJSP 表示（每工序 1 台设备） | 基准验证 |

> 命名对应：Hurink `sdata/mt06.fjs` = 经典 **FT06**（Fisher & Thompson 6×6，最优 55）；
> `sdata/mt10.fjs` = 经典 **FT10**（10×10，最优 930）；`sdata/la01–la40.fjs` = 经典
> **LA01–LA40**。已统一重命名为 `ft06.fjs`、`ft10.fjs`、`la01.fjs` … `la40.fjs`。

**备选下载源（GitHub，需代理）**：https://github.com/Lei-Kun/FJSP-benchmarks 、
https://github.com/SchedulingLab/fjsp-instances 、
官方基准页 https://people.idsia.ch/~monaldo/fjsp.html 、
FJSPLib（含上下界）https://scheduleopt.github.io/benchmarks/fjsplib 。

## 算例文本格式

预处理程序支持三种格式，均可**自动识别**（设备号解析后统一转 **0 基**）：

1. **Brandimarte 格式**（IDSIA / Monaldo 官方，FJSP 原始格式）
   ```
   第1行：工件数 设备数 [平均柔性]
   之后每行一个工件：工序数  k1 设备1 时间1 … 设备k1 时间k1  k2 …
   ```
   即每行开头是该工件的**工序数**（无独立工件号，工件按行序编号），随后每道工序 =
   `可选设备数 k + k 组(设备, 加工时间)`。设备号从 1 开始。

2. **设计说明书 §5.2 格式**（每行开头多「工件号 工序数」两个字段）
   ```
   1 3  2 1 3 2 5  1 3 4  1 2 6    # 工件1，3道工序；工序1:机1(3)/机2(5) …
   ```

3. **经典 JSP 格式**（FT / LA，或转换为 flexibility=1 的 FJSP）
   ```
   第1行：工件数 设备数
   之后每行一个工件，m 组 (设备号, 加工时间)，按工序顺序排列
   ```
   设备号 0/1 基自动识别。

## 数据预处理

预处理程序 [`data/preprocess.py`](data/preprocess.py) 完成：

1. 解析 Brandimarte / 设计说明书 / 经典 JSP 三种文本格式（自动识别）；
2. 数据完整性校验（可选设备非空、设备号越界、加工时间非正、可选设备重复）；
3. 规模统计（工件数、设备数、工序总数、平均柔性）；
4. 输出统一 JSON 到 `data/processed/`，并生成 `index.json` 索引。

```bash
python data/preprocess.py            # 处理 data/raw/ 下全部算例（已生成 processed/）
python data/preprocess.py --selftest # 内置 FT06 自测
```

**预处理产物**（`data/processed/<name>.json`，每个算例一份）：

```json
{
  "name": "mk01",
  "num_jobs": 10,
  "num_machines": 6,
  "total_operations": 55,
  "avg_flexibility": 2.09,
  "known_best_makespan": 40,
  "jobs": [
    {
      "job_id": 0,
      "num_operations": 6,
      "operations": [
        {"eligible_machines": [0, 1, 3], "processing_times": [5, 3, 4]}
      ]
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `name` | 算例名（小写，如 `mk01`、`ft06`、`la01`） |
| `num_jobs` / `num_machines` | 工件数 / 设备数 |
| `total_operations` | 工序总数 |
| `avg_flexibility` | 平均每道工序可选设备数（JSP 为 1.0） |
| `known_best_makespan` | 已知最优 / 最优上界（未收录为 `null`） |
| `jobs[].operations[]` | 每道工序的 `eligible_machines` 与 `processing_times`（按下标对齐，0 基设备号） |

`index.json` 为全部算例的规模统计索引（含已知最优），算法模块（M1）可直接读取这些
JSON，无需再解析原始文本。

## AI 使用披露

本项目的 AI 辅助开发对话记录统一归档于 `prompt/` 目录，以 **JSON Lines（`.jsonl`）**
格式保存 Claude Code 会话原始记录（即任务书要求的「json 文件」形式），作为过程档案留痕。
按开发阶段分文件：`stage-1-数据资源整理.jsonl`、`stage-2-方案设计.jsonl` 等。

> **重要提醒**：AI 对话过长会发生「上下文压缩」，早期原始记录会被摘要化、无法恢复。
> 每个阶段结束前、且对话尚未被压缩时，务必及时把本机
> `C:\Users\ASUS\.claude\projects\C--Users-ASUS\<sessionId>.jsonl` 复制到 `prompt/`
> 并改名为阶段文件，避免早期问答细节丢失。
