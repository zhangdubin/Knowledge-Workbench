<template>
  <div ref="host" class="echart-host" :style="{ height }" />
</template>

<script setup>
/**
 * ECharts 薄封装
 *
 * 三件必须做的事，缺一个图表就会「看着能用但不对」：
 *   1. 主题切换后重画 —— 否则暗色下坐标轴文字还是深灰，看不见
 *   2. 容器尺寸变化后 resize —— 侧边栏折叠、窗口拉伸都要跟
 *   3. 卸载时 dispose —— 不然频繁进出驾驶舱会漏实例
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
// 按需引入：整包 echarts 会多出 ~700KB，而驾驶舱只用柱/折/饼/仪/雷这几类图
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, GaugeChart, RadarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { isDark } from '../utils/theme'

echarts.use([
  BarChart, LineChart, PieChart, GaugeChart, RadarChart,
  GridComponent, TooltipComponent, LegendComponent,
  CanvasRenderer,
])

const props = defineProps({
  option: { type: Object, default: () => ({}) },
  height: { type: String, default: '260px' },
})

const emit = defineEmits(['click', 'ready'])

const host = ref(null)
const chart = shallowRef(null)
let ro = null

function render() {
  if (!chart.value) return
  // notMerge：卡片换数据源时旧 series 必须消失，否则会残留上一个图的形状
  chart.value.setOption(props.option || {}, { notMerge: true })
}

onMounted(() => {
  chart.value = echarts.init(host.value, null, { renderer: 'canvas' })
  render()
  chart.value.on('click', (p) => emit('click', p))
  emit('ready', chart.value)

  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => chart.value?.resize())
    ro.observe(host.value)
  }
})

// 主题切换：CSS 变量变了，option 里已经写死的颜色不会自己更新，
// 所以让使用方依赖 isDark 重算 option，这里再重画一次兜底。
watch(isDark, () => render())
watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  ro?.disconnect()
  chart.value?.dispose()
  chart.value = null
})

defineExpose({ getChart: () => chart.value, resize: () => chart.value?.resize() })
</script>

<style scoped>
.echart-host { width: 100%; }
</style>
