var options = {
  series: [
    {
      data: [
        {
          x: "Development",
          y: [3000, 5000],
        },
        {
          x: "Testing",
          y: [3200, 4800],
        },
        {
          x: "Design",
          y: [2800, 4500],
        },
        {
          x: "Deployment",
          y: [3500, 6000],
        },
        {
          x: "Documentation",
          y: [4000, 5200],
        },
        {
          x: "Maintenance",
          y: [4500, 7000],
        },
        {
          x: "Research",
          y: [3800, 5600],
        },
      ],
    },
  ],
  chart: {
    height: 350,
    type: "rangeBar",
    toolbar: {
      show: false,
    },
  },
  colors: ["#5fb1f4", "#a186e4"],
  plotOptions: {
    bar: {
      horizontal: true,
      isDumbbell: true,
      dumbbellColors: [["#5fb1f4", "#a186e4"]],
      barHeight: "3",
    },
  },
  legend: {
    show: true,
    showForSingleSeries: true,
    position: "top",
    horizontalAlign: "left",
    customLegendItems: ["In progress", "Completed"],
  },
  fill: {
    type: "gradient",
    gradient: {
      gradientToColors: ["#a186e4"],
      inverseColors: false,
      stops: [0, 100],
    },
  },
  grid: {
    xaxis: {
      lines: {
        show: true,
      },
    },
    yaxis: {
      lines: {
        show: false,
      },
    },
  },
};

var chart = new ApexCharts(document.querySelector("#tasks"), options);
chart.render();