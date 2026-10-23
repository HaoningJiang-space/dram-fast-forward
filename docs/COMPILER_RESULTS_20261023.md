# 调度区域编译第一轮：受限精确性验证通过，真实窗口未超过hybrid

2026-10-23。分支`research/schedule-compiler`。实现合同见
[SCHEDULE_COMPILER.md](SCHEDULE_COMPILER.md)，原始小型证据见
[summary_v5.json](../results/compiler_20261023/evidence/summary_v5.json)。

## 已实际完成

- 从真实`upgate/tile0`读取两个DMA范围，生成参数化二维整数资源关系；没有输入命令日志。
- 系统libisl证明Bank投影等价及三条时序归纳义务。编译器生成READ/WRITE的条件、发射递推
  和状态更新C++；普通控制器保留为不支持区域的精确回退。
- 冻结同一8-bank共享总线物理配置，对39个用例各运行三种生成策略与独立reference，
  **117次逐字节差分、49,243个资源退出状态全部通过**。覆盖新请求、水位切换、跨Row、
  刷新、闭环、20个随机种子、真实tile范围和历史完整捕获窗口。
- 全部命令、接纳/拒绝、callback及终态比较；完整E事件哈希也与上一轮冻结参考相同。
- 独立总线checker核对471,344个命令、214,176个数据命令、448次读写转换、448次刷新和
  129,619次四ACT窗口检查，均通过。共享总线没有被省略。
- 本地5项编译器测试通过，包括5000个随机入口与独立逐拍ready/oldest调度对照；故意令
  私有间隔大于共享间隔时，isl反例集合非空。它不等于对整个C++控制器作形式化证明。

早期v1在跳时落到刷新拍时未先退出编译区域，被差分拒绝。最终v5修复后重跑全部矩阵。
[失败证据](../results/compiler_20261023/evidence/failure_v1.json)保留。

## 性能：三次新进程CPU中位数

表内均相对同用例reference，数字大于1才是加速。小测试仅用于正确性，不混入性能汇总。

| 用例 | hybrid | 编译stride/RLE | 编译资源投影 | 编译动态资源分类 |
|---|---:|---:|---:|---:|
| E：224,896项捕获请求 | 1.51× | 1.11× | **0.88×** | 1.22× |
| 真实tile权重DMA，2048请求 | 1.45× | 0.94× | 1.07× | 1.11× |
| 同一真实行几何的重复读取控制 | 1.16× | 2.43× | 2.22× | 2.43× |
| A：10万规则READ＋恢复尾段 | 5.24× | 7.32× | 7.25× | 6.78× |
| C：10万交错bank请求＋恢复尾段 | 1.26× | 2.59× | 2.93× | 3.03× |

这是仿真循环CPU，不是芯片吞吐。E的整进程CPU相对reference分别为hybrid **1.51×**、
资源投影 **0.89×**、动态资源分类 **1.20×**。C的资源投影整进程CPU为2.67×。
完整原始样本均保留；短tile用例的样本波动明显，循环与整进程中位数排序还会不同，
不能凭微小整进程差异认定它超过hybrid。

## 编译开销与回本

| 工作 | CPU成本 |
|---|---:|
| DMA提取与isl资源投影 | 6.78 ms |
| 条件证明与代码生成 | 3.87 ms |
| 完整C++构建/链接 | 11.228 s |
| 合计 | **11.239 s** |

C++构建wall为13.34 s。当前重编整个translation unit，尚未实现独立小内核增量编译。
按相同输入重复使用、整进程CPU中位数估计，资源投影方案在C约**29次**、A约**611次**
才能收回编译成本。实际数据和入口变化可能改变收益；这是条件估计，不是系统保证。
E每次都慢于hybrid，**不存在有限回本次数**。
短tile的约1.9万次中位数回本估计对噪声敏感，不将它作为正收益证据。

## 负结果具体说明了什么

**首先，当前片段尚未证明多面体是性能来源。** 同一生成时序内核使用动态资源分类时，
无需约束地址序列或Bank周期，也能建立本轮相同的时序条件。它在C与资源投影相近，在E
明显更好。资源投影仍有压缩表达与参数化证明价值，但这些价值没有自动成为运行时收益。

**第二，单个循环的资源周期不能直接当成合并队列的顺序。** E的资源模式匹配失败654,404次，
仅1,873个数据命令进入生成区间；动态资源分类有73,385个。前者几乎没有削减重复调度：
prerequisite扫描由reference的2,692,593次仅降到2,674,952次，动态分类为2,095,906次，
hybrid为600,670次。当前路径的失效/识别成本与大比例精确回退足以抵消局部收益。

这里还存在明确的前端范围差异：真实tile实验将原始逻辑DMA范围直接映射到本PoC共享fixture；
E则是原native已经分配endpoint并转换地址后的捕获流。当前编译器尚未完整导入原native的
逻辑→物理地址变换、多生产者及其合流关系。因此不能把E的低覆盖全部归因于“真实工作负载
缺少多面体结构”，也不能把这次E回放称为已经完成的全加速器编译。

**第三，真实tile本身就暴露了混合命令需求。** 其128行权重DMA会跨Row；一次性释放并承担
真实回压时，资源投影方案只有6/2048个数据命令进入生成区域。Bank投影具有周期性，
并不使PRE/ACT、active队列和新的Row依赖消失。当前规则只编译不改变row状态的同类命令。

**第四，整个系统未必有很多可跳空拍。** 完整E的64个独立memory实例在全局时间上交错，
生成路径仅跳过28个全局周期。单个资源有规律，不意味着可以让全部资源的时间一起跳跃。

## 研究决策

保留编译驱动的研究定位，但本轮只能称为**受限调度区域编译PoC**。不将其包装成已完成的
通用符号调度编译器，也不以规则READ加速覆盖完整E的负结果。

下一步的算法问题收敛为：从多个结构化producer及实际地址变换构造资源关系，在含
PRE/ACT、阶段切换的区域中自动推导调度条件；区域内部时间可独立求值，随后按依赖与
回调边界合成。当前逐次扫描运行队列的入口验证也应由可审计的结构化producer合同替代。

如果这些能力仍能由简单资源分类同等完成，应据实调整多面体在方法中的角色。现在没有
证据支持把它指定为唯一核心，也没有因本轮窄片段失败而放弃它的依据。

## 复现

现有Python环境、系统libisl与冻结Linux依赖即可。以下输入IR和模型来自本轮归档；提取
完整源tile不是重新编译生成代码的必要条件。需要重新提取时使用`extract_dma_ir --tiles`。

```sh
export PYTHONPATH="$PWD/src"
python3 -m unittest discover -s tests -v
python3 -m dram_fast_forward.schedule_compile \
  --program results/compiler_20261023/evidence/extracted_v2/memory_ir.json \
  --model results/compiler_20261023/evidence/static_model/timing.json \
  --output runs/compiler-reproduce/generated
python3 -m dram_fast_forward.build \
  --source dependencies/direct400-linux \
  --ramulator dependencies/direct400-linux/ramulator \
  --compiled-header runs/compiler-reproduce/generated/generated_schedule.hh \
  --output runs/compiler-reproduce/build
python3 -m dram_fast_forward.compiler_study \
  --binary runs/compiler-reproduce/build/dram_poc \
  --dram-yaml configs/shared-bus-8bank.yaml \
  --memory-ir results/compiler_20261023/evidence/extracted_v2/memory_ir.json \
  --patterns tile_weight resource_repeat --repeats 3 \
  --output runs/compiler-reproduce/comparison
```

完整运行命令在`pipeline_v5.receipt.json`，原始trace及状态日志留在
`/Orion/jian/jhn/dram-fast-forward/runs/compiler_001`，大文件SHA见`large_artifacts.json`。
