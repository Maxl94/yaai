<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { CategoricalData } from '@/types'
import { aggregateTopCategories, escapeHtml, isHorizontalLayout } from '@/utils/chartFormat'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: CategoricalData
  fieldName: string
}>()

const bars = computed(() => aggregateTopCategories(props.data.categories))
const horizontal = computed(() => isHorizontalLayout(bars.value.map((b) => b.label)))

// Horizontal layout needs ~20px per bar; vertical keeps the compact default.
const chartHeight = computed(() => (horizontal.value ? Math.max(200, 40 + bars.value.length * 20) : 200))

const option = computed(() => {
  const items = bars.value
  const isHorizontal = horizontal.value

  const labelAxis = {
    type: 'category',
    data: items.map((b) => b.label),
    inverse: isHorizontal,
    axisLabel: {
      fontSize: 10,
      interval: 0,
      overflow: 'truncate',
      width: isHorizontal ? 90 : 60,
    },
  }
  const valueAxis = { type: 'value', name: 'Count' }

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { dataIndex: number }[]) => {
        const bar = items[params[0]?.dataIndex ?? 0]
        if (!bar) return ''
        return `${escapeHtml(bar.label)}<br/>Count: ${bar.count} (${bar.percentage.toFixed(1)}%)`
      },
    },
    grid: {
      left: '3%',
      right: '6%',
      bottom: '3%',
      containLabel: true,
    },
    xAxis: isHorizontal ? valueAxis : labelAxis,
    yAxis: isHorizontal ? labelAxis : valueAxis,
    series: [
      {
        name: 'Count',
        type: 'bar',
        data: items.map((b) => ({
          value: b.count,
          itemStyle: { color: b.otherCount ? '#fcd34d' : '#f59e0b' },
        })),
        barMaxWidth: 28,
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize :style="{ height: chartHeight + 'px' }" />
</template>
