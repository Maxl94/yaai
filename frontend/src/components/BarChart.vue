<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { CategoricalData } from '@/types'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: CategoricalData
  fieldName: string
}>()

const option = computed(() => {
  const categories = props.data.categories.slice(0, 10) // Top 10

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { dataIndex: number }[]) => {
        const idx = params[0]?.dataIndex ?? 0
        const cat = categories[idx]
        if (!cat) return ''
        return `${cat.value}<br/>Count: ${cat.count} (${cat.percentage.toFixed(1)}%)`
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
      data: categories.map((c) => c.value),
      axisLabel: {
        rotate: 45,
        fontSize: 10,
        interval: 0,
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
        data: categories.map((c) => c.count),
        itemStyle: {
          color: '#f59e0b',
        },
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 200px" />
</template>
