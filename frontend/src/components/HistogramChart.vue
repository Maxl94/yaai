<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { HistogramData } from '@/types'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: HistogramData
  fieldName: string
}>()

const option = computed(() => {
  const buckets = props.data.buckets
  
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { dataIndex: number }[]) => {
        const idx = params[0]?.dataIndex ?? 0
        const bucket = buckets[idx]
        if (!bucket) return ''
        return `${bucket.range_start.toFixed(2)} - ${bucket.range_end.toFixed(2)}<br/>Count: ${bucket.count}`
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
      data: buckets.map((b) => `${b.range_start.toFixed(1)}`),
      axisLabel: {
        rotate: 45,
        fontSize: 10,
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
        data: buckets.map((b) => b.count),
        itemStyle: {
          color: '#0d9488',
        },
        barWidth: '90%',
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 200px" />
</template>
