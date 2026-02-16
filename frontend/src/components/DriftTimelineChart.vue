<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { EChartsOption, SeriesOption } from 'echarts'
import type { DriftResult } from '@/types'
import { useECharts } from '@/composables/useECharts'

interface Props {
  results: DriftResult[]
  threshold?: number
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  threshold: 0.1,
  height: 400,
})

const chartRef = ref<HTMLElement | null>(null)
const { initChart, setOption } = useECharts(chartRef)

function buildChart() {
  if (!chartRef.value || props.results.length === 0) return

  initChart()

  // Group results by field
  const fieldMap = new Map<string, DriftResult[]>()
  props.results.forEach((r) => {
    if (!fieldMap.has(r.field_name)) {
      fieldMap.set(r.field_name, [])
    }
    fieldMap.get(r.field_name)!.push(r)
  })

  // Sort each field's results by date
  fieldMap.forEach((results) => {
    results.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  })

  // Build series for each field
  const series: SeriesOption[] = []
  const legendData: string[] = []
  const colors = ['#0d9488', '#f59e0b', '#38bdf8', '#10b981', '#fb923c', '#2dd4bf', '#a78bfa', '#f472b6']
  let colorIndex = 0

  fieldMap.forEach((results, fieldName) => {
    legendData.push(fieldName)
    const color = colors[colorIndex % colors.length]
    colorIndex++

    // Use scatter for single points, line for multiple points
    series.push({
      name: fieldName,
      type: results.length === 1 ? 'scatter' : 'line',
      data: results.map((r) => ({
        value: [r.created_at, r.score],
        itemStyle: r.is_drifted
          ? {
              color: color,
              borderColor: '#dc2626',
              borderWidth: 3,
            }
          : { color: color },
      })),
      symbol: 'circle',
      symbolSize: (value: number[], params: { dataIndex: number }) => {
        const result = results[params.dataIndex]
        return result?.is_drifted ? 14 : 8
      },
      emphasis: {
        focus: 'series',
        scale: 1.3,
      },
      lineStyle: {
        width: 2,
        color: color,
      },
      itemStyle: {
        color: color,
      },
    })
  })

  // Add threshold line
  series.push({
    name: 'Threshold',
    type: 'line',
    data: [],
    markLine: {
      silent: true,
      symbol: 'none',
      lineStyle: {
        color: '#ff4444',
        type: 'dashed',
        width: 2,
      },
      data: [
        {
          yAxis: props.threshold,
          label: {
            formatter: `Threshold: ${props.threshold}`,
            position: 'end',
          },
        },
      ],
    },
  })

  const option: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e5e7eb',
      borderWidth: 1,
      textStyle: {
        color: '#374151',
        fontSize: 12,
      },
      formatter: (params: unknown) => {
        const items = params as { seriesName: string; value: [string, number]; color: string }[]
        if (!items[0]) return ''
        const d = new Date(items[0].value[0])
        const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        let html = `<div style="font-weight: 600; margin-bottom: 6px; color: #111827;">${dateStr}</div>`
        items.forEach((item) => {
          if (item.seriesName !== 'Threshold') {
            const drifted = item.value[1] > props.threshold
            const statusColor = drifted ? '#dc2626' : '#16a34a'
            const statusText = drifted ? 'Drift' : 'Stable'
            html += `<div style="display: flex; align-items: center; gap: 6px; margin: 3px 0;">
              <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: ${item.color};${drifted ? ' border: 2px solid #dc2626;' : ''}"></span>
              <span style="flex: 1; color: #4b5563;">${item.seriesName}</span>
              <span style="font-weight: 500;">${item.value[1].toFixed(4)}</span>
              <span style="font-size: 11px; font-weight: 500; color: ${statusColor};">${statusText}</span>
            </div>`
          }
        })
        return html
      },
    },
    legend: {
      data: legendData,
      type: 'scroll',
      bottom: 0,
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
          const d = new Date(value)
          return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        },
      },
    },
    yAxis: {
      type: 'value',
      name: 'Drift Score',
      min: 0,
    },
    series,
  }

  setOption(option)
}

watch(
  () => [props.results, props.threshold],
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
