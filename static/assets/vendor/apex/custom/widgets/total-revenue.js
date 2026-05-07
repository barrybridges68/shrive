var options = {
  series: [
    {
      name: "This Week",
      data: [0, 20, 15, 19, 14, 25, 30],
    },
    {
      name: "Last Week",
      data: [0, 8, 19, 13, 26, 16, 25],
    }
  ],
  chart: {
    height: 90,
    type: "line",
    toolbar: {
      show: false,
    },
    sparkline: {
      enabled: true,
    },
  },
  colors: ["#1f66e0", "#64bbf4"],
  dataLabels: {
    enabled: false
  },
  stroke: {
    curve: 'smooth',
    width: 3,
    colors: ["#1f66e0", "#64bbf4"],
  },
  grid: {
    show: false,
  },
  tooltip: {
    y: {
      formatter: function (val) {
        return val;
      },
    },
    theme: 'dark',
  },
};

var chart = new ApexCharts(document.querySelector("#total-revenue"), options);

chart.render();
