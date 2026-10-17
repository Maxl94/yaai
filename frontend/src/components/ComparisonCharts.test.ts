import { describe, it, expect, vi } from "vitest";
import type { Component } from "vue";
import { mount } from "@vue/test-utils";
import OverlaidHistogram from "@/components/OverlaidHistogram.vue";
import GroupedBarChart from "@/components/GroupedBarChart.vue";
import type { CategoricalData, HistogramData } from "@/types";

vi.mock("vue-echarts", async () => {
  const { defineComponent, h } = await import("vue");
  return {
    default: defineComponent({
      name: "VChartStub",
      props: { option: { type: Object, required: true } },
      setup: () => () => h("div"),
    }),
  };
});

type Option = {
  xAxis: { type: string };
  yAxis: { type: string };
  series: { data: ({ value: number | null } | number | null)[] }[];
  tooltip: { formatter: (params: unknown[]) => string };
};

const histogram = (counts: number[]) =>
  ({
    buckets: counts.map((count, i) => ({
      range_start: i,
      range_end: i + 1,
      count,
    })),
    statistics: {},
  }) as unknown as HistogramData;

const categorical = (label: string, count: number) =>
  ({
    categories: [{ value: label, count, percentage: 100 }],
    statistics: {},
  }) as unknown as CategoricalData;

function optionOf(component: Component, props: object): Option {
  const wrapper = mount(component, {
    props: { fieldName: "f", logScale: true, ...props },
  });
  return wrapper
    .findComponent({ name: "VChartStub" })
    .props("option") as Option;
}

describe("comparison charts with log scale", () => {
  it("OverlaidHistogram uses a log y-axis and drops zero counts", () => {
    const option = optionOf(OverlaidHistogram, {
      dataA: histogram([0, 4]),
      dataB: histogram([2, 0]),
    });
    expect(option.yAxis.type).toBe("log");
    expect(option.series[0]!.data).toMatchObject([
      { value: null },
      { value: 4 },
    ]);
  });

  it("GroupedBarChart puts the log axis on x in horizontal layout and tooltips show the real 0", () => {
    const option = optionOf(GroupedBarChart, {
      dataA: categorical("a very long category label", 5),
      dataB: categorical("other", 0),
    });
    expect(option.xAxis.type).toBe("log");
    expect(option.yAxis.type).toBe("category");
    const rows = [
      { seriesName: "Period A", value: 5, marker: "", dataIndex: 0 },
      { seriesName: "Period B", value: null, marker: "", dataIndex: 0 },
    ];
    expect(option.tooltip.formatter(rows)).toContain("Period B: 0");
  });
});

describe("OverlaidHistogram legend", () => {
  it("colors each series like its bars so the legend matches", () => {
    const option = optionOf(OverlaidHistogram, {
      dataA: histogram([1]),
      dataB: histogram([2]),
      logScale: false,
    }) as unknown as {
      series: { itemStyle: { color: string }; data: { itemStyle: { color: string } }[] }[];
    };
    for (const s of option.series) {
      expect(s.itemStyle.color).toBe(s.data[0]!.itemStyle.color);
    }
    expect(option.series[0]!.itemStyle.color).not.toBe(option.series[1]!.itemStyle.color);
  });
});
