# DRAM Fast-Forward

公开研究：**存在并发、共享总线和动态请求时，用符号执行与依赖图加速精确DRAM模拟。**
本地独立目录：`/Users/haoning/project/dram-fast-forward`。

当前主线：**结构化访存与资源语义 → 条件调度区域 → 精确时序代码**。
研究分支`research/schedule-compiler`，从真实tile描述出发，使用系统libisl分析资源关系。
incremental/hybrid保留为基线；增加stride/RLE及不依赖多面体的资源分类对照。
[编译器合同与边界](docs/SCHEDULE_COMPILER.md)、[当前实验](docs/COMPILER_RESULTS_20261023.md)。

上一阶段入口：[方法论](docs/RESEARCH_METHOD.md)、[第二轮实验](docs/INTERFERENCE_20261023.md)。
首轮隔离守卫的0%不能否定多面体路线；固定顺序oracle图求值也不能当成在线加速。

## 上一阶段完整捕获窗口

224,896项局部FFN请求，三次新进程循环CPU中位数；不是整模型或芯片token/s：

| 参考配置 | 增量更新 | 符号计划 | 符号＋增量 | 符号READ覆盖 |
|---|---:|---:|---:|---:|
| 原独立TSV bank | 1.45× | 1.41× | 1.53× | 61.20% |
| 8bank共享总线 | 1.49× | 1.20× | 1.53× | 34.16% |

共享组合的整进程CPU加速为1.49×。66案例、198次计划/参考比较、284,039次资源退出
状态比较通过。高压到达存在负结果，不能全局默认启用新策略。

固定顺序图加入队列策略后精确重现696,240个命令/回调节点；Python建图数秒，遍历数毫秒，
尚未解决低成本在线依赖发现。[全部测量](results/interference_20261023/MEASUREMENTS.md)。

## 代码布局

```text
src/dram_fast_forward/
  native/                 C++引擎、符号计划、共享映射、CSR求值器
  build.py                固定输入构建；profile_patch.py定义共享fixture
  common.py               公共IO、子进程与CPU计时
  workloads.py            合成模式与真实请求窗口
  interference.py         当前在线方案的差分和计时入口
  oracle_graph.py          固定顺序诊断，在线路径不读取它
  check_bus.py            独立总线、ACT窗口和刷新检查
  fuzz_interference.py     混合/闭环压力测试
  guard_regressions.py     写阈值、读到达和row-miss检查
  polyhedral.py           系统libisl的整数资源投影与证明检查
  extract_dma_ir.py       从模拟前tile描述提取二维DMA循环
  schedule_compile.py     条件/递推/状态代码生成
  compiler_study.py       编译器、stride/RLE与动态资源对照
configs/                  独立TSV和共享总线两个显式配置
docs/                     方法、报告、来源与迁移说明
results/                  按实验冻结的小型证据
tools/                    输入导出与归档核对
dependencies/,build/,runs/ 大型本地生成物，不进入Git
```

`run.py`、`fuzz.py`、`summarize.py`保留首轮控制；捕获工具是可选LeanWafer适配，
不是核心模拟器的Python依赖。原40案例及[来源](docs/ORIGIN.json)保持冻结。
源码已演进；整理后的二进制与本轮测量版本相同，不再声称源码仍等同初次提取版本。

## 使用现有环境

不需要安装 Python 包或新建环境。Python脚本使用标准库，要求 Python≥3.10；编译器另外调用
系统已有的`libisl`，执行生成内核不需要它。C++构建要求
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

## 当前实验入口

同一构建支持两个配置。对`interference`显式提供`--binary`、`--dram-yaml`、全新
`--output`，可用`--patterns E --counts 224896 --real-trace PATH --repeats 3`测试完整窗口。
共享配置为`configs/shared-bus-8bank.yaml`，是竞争验证fixture，不是已校准商业DDR器件。

```sh
export PYTHONPATH="$PWD/src"
python3 -m dram_fast_forward.interference --help
c++ -O3 -std=c++20 src/dram_fast_forward/native/graph_solve.cc -o build/graph_solve
python3 -m dram_fast_forward.oracle_graph --help
python3 -m dram_fast_forward.check_bus --help
```

`fuzz_interference --seeds 20`与`guard_regressions`也要求显式binary/YAML/output。
图分析使用case中的`bank_affine_reference`及`bank_affine_events.bin.gz`；
`--ablate-shared-bus`是故意漏算总线的负对照，不参与在线性能表。

## 观察接口与后续

严格比较命令、接纳回压、callback和恢复状态。当前计划不读取oracle日志，不提前提交
未来事件；若调用方要求N次独立callback，反馈成本至少为Ω(N)。不靠少发事件获得加速。

继续研究低成本依赖发现、按资源安排事件和更一般的符号区间，不因一次守卫失败放弃
多面体。当前窗口是三次局部Up/Gate的捕获请求，不能替代全加速器闭环验证。
