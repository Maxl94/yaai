<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { EChartsOption } from 'echarts'
import type { InferenceVolumeBucket } from '@/types'
import { useECharts } from '@/composables/useECharts'

interface Props {
  data: InferenceVolumeBucket[]
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 250,
})

const chartRef = ref<HTMLElement | null>(null)
const { initChart, setOption, clear } = useECharts(chartRef)

function buildChart() {
  if (!chartRef.value || props.data.length === 0) {
    clear()
    return
  }

  initChart()

  const option: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const items = params as { value: [string, number] }[]
        if (!items[0]) return ''
        const date = new Date(items[0].value[0])
        return `<strong>${date.toLocaleString()}</strong><br/>Count: ${items[0].value[1]}`
      },
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '15%',
      containLabel: true,
    },
    xAxis: {
      type: 'time',
      name: 'Time',
      axisLabel: {
        formatter: (value: number) => {
          const date = new Date(value)
          return `${date.getMonth() + 1}/${date.getDate()}\n${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`
        },
      },
    },
    yAxis: {
      type: 'value',
      name: 'Count',
      min: 0,
    },
    series: [
      {
        type: 'bar',
        data: props.data.map((d) => ({
          value: [d.bucket, d.count],
        })),
        itemStyle: {
          color: '#0d9488',
        },
        emphasis: {
          itemStyle: {
            color: '#0f766e',
          },
        },
      },
    ],
  }

  setOption(option)
}

watch(
  () => props.data,
  () => buildChart(),
  { deep: true }
)

onMounted(() => {
  buildChart()
})
</script>

<template>
  <div ref="chartRef" :style="{ width: '100%', height: height + 'px' }"></div>
</template>
