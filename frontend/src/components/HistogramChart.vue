<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { HistogramData } from '@/types'
import { bucketTooltipTitle, formatBucketLabels } from '@/utils/chartFormat'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: HistogramData
  fieldName: string
}>()

const BAR_COLOR = '#0d9488'
const OUTLIER_COLOR = 'rgba(13, 148, 136, 0.35)'

const option = computed(() => {
  const buckets = props.data.buckets

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { dataIndex: number }[]) => {
        const bucket = buckets[params[0]?.dataIndex ?? 0]
        if (!bucket) return ''
        return `${bucketTooltipTitle(bucket)}<br/>Count: ${bucket.count}`
      },
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: formatBucketLabels(buckets),
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
        name: 'Count',
        type: 'bar',
        data: buckets.map((b) => {
          const isOutlier = b.is_underflow || b.is_overflow
          return {
            value: b.count,
            itemStyle: isOutlier
              ? { color: OUTLIER_COLOR, borderColor: BAR_COLOR, borderType: 'dashed', borderWidth: 1 }
              : { color: BAR_COLOR },
          }
        }),
        barWidth: '90%',
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 200px" />
</template>
