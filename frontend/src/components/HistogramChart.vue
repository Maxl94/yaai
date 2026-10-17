<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { HistogramData } from '@/types'
import {
  DIRECTION_COLORS,
  bucketTooltipTitle,
  countAxis,
  countBarStyle,
  formatBucketLabels,
  plotCount,
  type FieldDirection,
} from '@/utils/chartFormat'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: HistogramData
  fieldName: string
  direction?: FieldDirection
  logScale?: boolean
}>()

const option = computed(() => {
  const buckets = props.data.buckets
  const { base: BAR_COLOR, muted: OUTLIER_COLOR } = DIRECTION_COLORS[props.direction ?? 'input']

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
    yAxis: countAxis(props.logScale),
    series: [
      {
        name: 'Count',
        type: 'bar',
        data: buckets.map((b) => {
          const isOutlier = b.is_underflow || b.is_overflow
          return {
            value: plotCount(b.count, props.logScale),
            itemStyle: isOutlier
              ? { color: OUTLIER_COLOR, borderColor: BAR_COLOR, borderType: 'dashed', borderWidth: 1 }
              : { color: BAR_COLOR },
          }
        }),
        barWidth: '90%',
        ...countBarStyle(props.logScale),
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 200px" />
</template>
