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
        'Authorization': 'Bearer 4a1bab46af94dd9266a4a070715ed3fdf4ad57679e7ce80ed82a3962e5891714'
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
