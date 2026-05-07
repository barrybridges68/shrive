$(document).ready(function () {
  // Credit Card
  $('#creditCard').inputmask("9999 9999 9999 9999");
  $('#expiryDate').inputmask("99/99");
  $('#cvv').inputmask("999");

  // Phone Numbers
  $('#usPhone').inputmask("(999) 999-9999");
  $('#intlPhone').inputmask("99 999 999 9999");

  // Date and Time
  $('#dateInput').inputmask("99/99/9999");
  $('#timeInput').inputmask("99:99:99");

  // Currency and Numbers
  $('#currencyInput').inputmask("numeric", {
    radixPoint: ".",
    groupSeparator: ",",
    digits: 2,
    autoGroup: true,
    prefix: ''
  });
  $('#percentInput').inputmask("numeric", {
    min: 0,
    max: 100,
    suffix: ''
  });

  // Network
  $('#ipAddress').inputmask("999.999.999.999");
  $('#macAddress').inputmask("**:**:**:**:**:**");

  // Personal IDs
  $('#ssnInput').inputmask("999-99-9999");
  $('#taxId').inputmask("99-9999999");
});