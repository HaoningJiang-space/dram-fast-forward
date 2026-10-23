# DRAM Fast-Forward

独立研究 **如何更快地、精确地模拟 DRAM**。本地目录为
`/Users/haoning/project/dram-fast-forward`，与 LeanWafer 仓库分开维护。

比较三条路线：跳过无变化周期的 event-driven、按状态失效的 incremental prerequisite
更新，以及带充分安全守卫的同 row READ 数学批量执行。基准是冻结的 Ramulator
FR-FCFS、地址映射和刷新；不改变被模拟硬件来制造主机加速。

## 已有证据

2026-10-23 PoC：40 个差分 case、21,977 次 fast-exit 状态比较通过，覆盖命令顺序/周期、
请求接纳回压、callback、刷新恢复与合成闭环。下表为循环 CPU 加速，不是芯片 token/s：

| 输入 | event | incremental | symbolic |
|---|---:|---:|---:|
| 最规则同 row READ，100万请求 | 2.00× | 1.92× | 5.82× |
| 真实 FFN 完整224,896项窗口 | 1.04× | 1.29× | 1.01×，批量覆盖0% |

计入初始化等成本，前者 symbolic 为4.39×，后者 incremental 为1.25×。
真实地址同 row 局部性81.56%并不等于可以安全批量。完整说明、负结果与适用边界：
[研究报告](docs/POC_20261023.md)、[全部实测](results/20261023/MEASUREMENTS.md)、
[实现和严格守卫](docs/IMPLEMENTATION.md)。

这些是从原仓库提取的历史测量，不能改标成新仓库新跑的结果。来源提交和原始文件哈希见
[ORIGIN.json](docs/ORIGIN.json)。当前源码中 C++ solver、hooks 与差分 driver 保持原字节。

## 布局

```text
src/dram_fast_forward/  C++ solver、构建、差分、捕获和分析工具
configs/               冻结物理配置
docs/                  方法、实验与来源
results/20261023/      小型原始证据、配置及二进制身份
tools/                 独立输入导出和证据检查
dependencies/          忽略的、平台相关的冻结输入包
build/、runs/          忽略的新构建与实验输出
```

## 使用现有环境

不需要安装 Python 包或新建环境。Python脚本使用标准库，要求 Python≥3.10；C++构建要求
支持 C++20 的编译器与冻结的依赖。推荐直接从仓库根目录运行：

```sh
export PYTHONPATH="$PWD/src"
python3 tools/check_archive.py
python3 -m dram_fast_forward.run --help
```

现阶段的物理模型是 LeanWafer 当时使用的自定义 direct-bank Ramulator，不是任意上游
Ramulator 配置。**研究代码独立维护，物理输入仍必须显式固定。** 根目录不包含其他
LeanWafer Python 模块，也不需要将原工程放入 `PYTHONPATH`。

## 独立冻结输入包

为了不依赖原工程的绝对构建路径，在原输入仍可访问的服务器上一次性导出：

```sh
PY=/home/jian/miniconda3/envs/pytorchsim_env/bin/python
$PY tools/export_frozen_inputs.py \
  --poc-build /Orion/jian/jhn/astra/runs/dram_fast_forward_poc_20261023_001/build_v10 \
  --output "$PWD/dependencies/direct400-linux"
```

导出器逐项核对原 manifest 的 SHA256，仅复制五份物理源码、编译所需第三方头文件和
支持对象/静态库，并把输入 manifest 改为 `${BUNDLE}` 根目录。输入包可以移动；之后构建
不再读取原 LeanWafer 构建目录。它包含 Linux 已编译对象，**不能直接用于 macOS**，也不
意味着已经完成从通用上游 Ramulator 源码构建的支持。依赖包和大型 trace 不提交到 Git。

在兼容的 Linux 工具链上构建：

```sh
export PYTHONPATH="$PWD/src"
$PY -m dram_fast_forward.build \
  --source "$PWD/dependencies/direct400-linux" \
  --ramulator "$PWD/dependencies/direct400-linux/ramulator" \
  --output "$PWD/build/poc"
$PY -m dram_fast_forward.run \
  --binary "$PWD/build/poc/dram_poc" --dram-yaml "$PWD/configs/direct-bank-d32.yaml" \
  --output "$PWD/runs/example" --patterns A B C D --counts 10000 --repeats 3
```

真实 E trace 和原始大文件的 SHA/服务器位置见
[large_artifacts.json](results/20261023/evidence/large_artifacts.json)。使用 trace 时显式传
`--patterns E --real-trace PATH --counts 224896`；百万请求 E 只能标为周期扩展。

## 研究边界和后续

优先提高真实闭环下的增量调度效率，再评估每 controller 的事件维护；规则段批量先保留为
机制证明。不预设完整多面体编译或 GPU。每项新机制须保持完整事件和状态差分，计时需
区分循环 CPU、整进程 CPU、wall，以及真实负载覆盖率。

历史证据中的绝对路径用于追溯，不是当前 Python 导入依赖。迁移后的实际构建/运行验证
另列于 [RELOCATION.md](docs/RELOCATION.md)。原 LeanWafer 快照保留用于历史复现。
