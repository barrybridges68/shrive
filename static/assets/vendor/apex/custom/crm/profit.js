var options = {
  series: [
    {
      name: "2024",
      data: [1, 2, 1, 3, 2, 5, 3, 2, 2, 4, 3, 2],
    },
    {
      name: "2023",
      data: [-2, -1, -2, -1, -2, -1, -4, -2, -1, -3, -2, -1],
    },
  ],
  chart: {
    toolbar: {
      show: false,
    },
    type: "bar",
    height: 360,
    stacked: true,
  },
  colors: ["#52b5fb", "#ed83ff"],
  plotOptions: {
    bar: {
      horizontal: false,
      barHeight: "60%",
      columnWidth: "16%",
      borderRadius: [5],
      borderRadiusApplication: "end",
      borderRadiusWhenStacked: "all",
    },
  },
  dataLabels: {
    enabled: false,
  },
  legend: {
    show: false,
  },
  grid: {
    show: true,
    padding: {
      top: 0,
      bottom: 0,
      right: 10,
    },
    borderColor: "#3f4c5c",
    xaxis: {
      lines: {
        show: true,
      },
    },
    yaxis: {
      lines: {
        show: true,
      },
    },
  },
  xaxis: {
    axisBorder: {
      show: false,
    },
    axisTicks: {
      show: false,
    },
    categories: [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "July",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec"
    ],
  },
  yaxis: {
    tickAmount: 4,
    min: -5,
    max: 5,
  },
  tooltip: {
    y: {
      formatter: function (val) {
        return '$' + val + '' + 'k';
      },
    },
    theme: 'dark',
  },
};

var chart = new ApexCharts(document.querySelector("#profit"), options);

chart.render();
