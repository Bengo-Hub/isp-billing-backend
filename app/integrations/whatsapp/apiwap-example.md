import axios from 'axios';
const { data, error } = async () => {
  try {
    const { data } = await axios.post('https://api.apiwap.com/api/v1/whatsapp/send-message',
    {
      phoneNumber: '+254700000000',
      message: 'Test Hello',
      type: "text",
    },
    {
      headers: {
        'Authorization': 'Bearer <YOUR_APIWAP_API_KEY>'
      },
    })
    return {
      data,
    }
  } catch(err) {
    return {
      error: err.response.data ? err.response.data ? err.message
    }
  }
}
console.log(data, error)
