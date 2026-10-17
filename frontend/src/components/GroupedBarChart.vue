<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { CategoricalData } from '@/types'
import {
  aggregateGroupedCategories,
  categoryDisplayName,
  countAxis,
  countBarStyle,
  escapeHtml,
  isHorizontalLayout,
  plotCount,
} from '@/utils/chartFormat'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  dataA: CategoricalData
  dataB: CategoricalData
  fieldName: string
  labelA?: string
  labelB?: string
  logScale?: boolean
}>()

const bars = computed(() => aggregateGroupedCategories(props.dataA.categories, props.dataB.categories))
const horizontal = computed(() => isHorizontalLayout(bars.value.map((b) => b.label)))

// Horizontal layout needs ~30px per category (two bars); vertical keeps the compact default.
const chartHeight = computed(() => (horizontal.value ? Math.max(220, 60 + bars.value.length * 30) : 220))

type TooltipItem = { seriesName: string; value: number | null; marker: string; dataIndex: number }

const option = computed(() => {
  const items = bars.value
  const isHorizontal = horizontal.value
  const nameA = props.labelA || 'Period A'
  const nameB = props.labelB || 'Period B'

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
  const valueAxis = countAxis(props.logScale)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: TooltipItem[]) => {
        const bar = items[params[0]?.dataIndex ?? 0]
        if (!bar) return ''
        const rows = params.map((p) => `${p.marker} ${escapeHtml(p.seriesName)}: ${p.value ?? 0}`)
        return [escapeHtml(categoryDisplayName(bar.label, bar.otherCount)), ...rows].join('<br/>')
      },
    },
    legend: {
      data: [nameA, nameB],
      top: 0,
    },
    grid: {
      left: '3%',
      right: '6%',
      bottom: '3%',
      top: '15%',
      containLabel: true,
    },
    xAxis: isHorizontal ? valueAxis : labelAxis,
    yAxis: isHorizontal ? labelAxis : valueAxis,
    series: [
      {
        name: nameA,
        type: 'bar',
        data: items.map((b) => plotCount(b.countA, props.logScale)),
        itemStyle: { color: 'rgba(13, 148, 136, 0.7)' },
        barMaxWidth: 20,
        ...countBarStyle(props.logScale),
      },
      {
        name: nameB,
        type: 'bar',
        data: items.map((b) => plotCount(b.countB, props.logScale)),
        itemStyle: { color: 'rgba(245, 158, 11, 0.45)' },
        barMaxWidth: 20,
        ...countBarStyle(props.logScale),
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize :style="{ height: chartHeight + 'px' }" />
</template>
