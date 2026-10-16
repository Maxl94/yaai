<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { HistogramData } from '@/types'
import { bucketTooltipTitle, escapeHtml, formatBucketLabels } from '@/utils/chartFormat'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  dataA: HistogramData
  dataB: HistogramData
  fieldName: string
  labelA?: string
  labelB?: string
}>()

const COLOR_A = 'rgba(13, 148, 136, 0.7)'
const COLOR_B = 'rgba(245, 158, 11, 0.45)'

type TooltipItem = { dataIndex: number; seriesName: string; value: number; marker: string }

const option = computed(() => {
  const bucketsA = props.dataA.buckets
  const bucketsB = props.dataB.buckets
  const nameA = props.labelA || 'Period A'
  const nameB = props.labelB || 'Period B'

  // Both sides share the same edges; fall back to B if A has no data.
  const reference = bucketsA.length > 0 ? bucketsA : bucketsB

  const seriesData = (buckets: typeof bucketsA, color: string) =>
    buckets.map((b) => ({
      value: b.count,
      itemStyle:
        b.is_underflow || b.is_overflow
          ? { color, opacity: 0.5, borderColor: color, borderType: 'dashed', borderWidth: 1 }
          : { color },
    }))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: TooltipItem[]) => {
        const bucket = reference[params[0]?.dataIndex ?? 0]
        if (!bucket) return ''
        const rows = params.map((p) => `${p.marker} ${escapeHtml(p.seriesName)}: ${p.value}`)
        return [bucketTooltipTitle(bucket), ...rows].join('<br/>')
      },
    },
    legend: {
      data: [nameA, nameB],
      top: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '15%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: formatBucketLabels(reference),
      axisLabel: {
        fontSize: 10,
        interval: 'auto',
        hideOverlap: true,
        overflow: 'truncate',
        width: 56,
      },
    },
    yAxis: {
      type: 'value',
      name: 'Count',
    },
    series: [
      {
        name: nameA,
        type: 'bar',
        data: seriesData(bucketsA, COLOR_A),
        barWidth: '35%',
      },
      {
        name: nameB,
        type: 'bar',
        data: seriesData(bucketsB, COLOR_B),
        barWidth: '35%',
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 220px" />
</template>
