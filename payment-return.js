const message = document.querySelector('#paymentReturnMessage');
const orderDisplay = document.querySelector('#paymentReturnOrder');
const params = new URLSearchParams(location.search);
const payment = {order_nsu:params.get('order_nsu'), slug:params.get('slug'), transaction_nsu:params.get('transaction_nsu'), receipt_url:params.get('receipt_url')};
if (payment.order_nsu) orderDisplay.textContent = `Pedido ${payment.order_nsu}`;
if (!payment.order_nsu || !payment.slug || !payment.transaction_nsu) { message.textContent = 'Não recebemos os dados de confirmação. O dono poderá conferir o pagamento no painel InfinitePay.'; }
else {
  fetch('/api/payments/infinitepay/confirm', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payment)})
    .then(async response => { const result = await response.json(); if (!response.ok) throw new Error(result.error || ''); return result; })
    .then(result => { message.textContent = result.paid ? 'Pagamento confirmado com sucesso. Obrigada pela compra! ✨' : 'O pagamento ainda está sendo processado. Você pode conferir o status com a loja.'; })
    .catch(() => { message.textContent = 'Não foi possível confirmar automaticamente agora. Guarde o número do pedido e entre em contato com a loja.'; });
}
