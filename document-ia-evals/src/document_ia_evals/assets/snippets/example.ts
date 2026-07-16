import fetch from 'node-fetch'; // si < Node.js 18

const url = "URL_PLACEHOLDER";
const apiKey = "API_KEY_PLACEHOLDER";

const formData = new FormData();
FILE_CODE_PLACEHOLDER
OVERRIDE_CODE_PLACEHOLDER
METADATA_CODE_PLACEHOLDER

const response = await fetch(url, {
  method: 'POST',
  headers: {
    'X-API-KEY': apiKey,
  },
  body: formData
});

const data = await response.json();
console.log(data);
