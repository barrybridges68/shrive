// Morris Days
var day_data = [
  { period: "2016-10-01", licensed: 3213, "BootstrapGet": 887 },
  { period: "2016-09-30", licensed: 3321, "BootstrapGet": 776 },
  { period: "2016-09-29", licensed: 3671, "BootstrapGet": 884 },
  { period: "2016-09-20", licensed: 3176, "BootstrapGet": 448 },
  { period: "2016-09-19", licensed: 3376, "BootstrapGet": 565 },
  { period: "2016-09-18", licensed: 3976, "BootstrapGet": 627 },
  { period: "2016-09-17", licensed: 2239, "BootstrapGet": 660 },
  { period: "2016-09-16", licensed: 3871, "BootstrapGet": 676 },
  { period: "2016-09-15", licensed: 3659, "BootstrapGet": 656 },
  { period: "2016-09-10", licensed: 3380, "BootstrapGet": 663 },
];
Morris.Line({
  element: "dayData",
  data: day_data,
  xkey: "period",
  ykeys: ["licensed", "BootstrapGet"],
  labels: ["Licensed", "BootstrapGet"],
  resize: true,
  hideHover: "auto",
  gridLineColor: "#3f4c5c",
  pointFillColors: [
    "#e962a8", "#a271d7", "#628bf0", "#50c356", "#f9c851"
  ],
  pointStrokeColors: ["#ffffff"],
  lineColors: [
    "#e962a8", "#a271d7", "#628bf0", "#50c356", "#f9c851"
  ],
});
