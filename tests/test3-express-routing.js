// Test 3: Express routing test file
const express = require('express');
const app = express();

app.get('/test', (req, res) => {
  res.json({ status: 'ok', test: 3 });
});

module.exports = app;
