(() => {
  const form = document.querySelector('#orderForm');
  if (!form) return;
  const submit = form.querySelector('[type="submit"]');
  const confirmation = document.querySelector('#orderConfirmation');
  const info = document.createElement('section');
  let completedOrder = null;
  info.className = 'payment-methods';
  info.setAttribute('aria-labelledby', 'paymentMethodsTitle');
  info.innerHTML = '<div class="payment-methods-heading"><span class="payment-lock" aria-hidden="true">⌑</span><div><strong id="paymentMethodsTitle">Pagamento protegido</strong><small>Finalizado no ambiente seguro da InfinitePay</small></div></div>' +
    '<div class="payment-method-list"><div class="payment-method"><span class="payment-symbol" aria-hidden="true">▦</span><span><strong>Pix</strong><small>QR Code e Copia e Cola no checkout</small></span></div>' +
    '<div class="payment-method"><span class="payment-symbol" aria-hidden="true">▤</span><span><strong>Crédito</strong><small>Parcelamento conforme opções disponíveis</small></span></div></div>' +
    '<p class="payment-security-note">Na próxima tela, ao escolher Pix, a InfinitePay gera o QR Code e o Copia e Cola do pedido. Confira no checkout o prazo para pagar. Os dados do cartão são preenchidos diretamente na InfinitePay e não ficam salvos no site.</p>' +
    '<p class="payment-debit-note">Cartão de débito online não está disponível nesta integração.</p><p class="payment-error" role="alert" hidden></p>';
  submit.before(info);
  submit.innerHTML = 'Criar pedido e continuar <span>↗</span>';

  function showConfirmation(result) {
    form.querySelectorAll(':scope > *').forEach(element => {
      if (!element.classList.contains('close-button') && element.id !== 'orderConfirmation') element.hidden = true;
    });
    document.querySelector('#confirmedOrderNumber').textContent = result.id;
    confirmation.querySelector('h3').textContent = 'Pedido criado!';
    confirmation.querySelector('p:not(.eyebrow)').textContent = 'Seu pedido foi registrado. Para concluir a compra, escolha Pix ou cartão de crédito no checkout seguro da InfinitePay.';
    let amount = confirmation.querySelector('.payment-order-total');
    if (!amount) {
      amount = document.createElement('p');
      amount.className = 'payment-order-total';
      confirmation.insertBefore(amount, confirmation.querySelector('.payment-checkout-action'));
    }
    const formatted = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format((result.total_cents || 0) / 100);
    amount.textContent = 'Total do pedido: ' + formatted;
    let link = confirmation.querySelector('.payment-checkout-action');
    if (!link) {
      link = document.createElement('a');
      link.className = 'button button-dark full-width payment-checkout-action';
      link.textContent = 'Ir para pagamento seguro ↗';
      confirmation.append(link);
    }
    link.href = result.checkout_url;
    confirmation.hidden = false;
  }

  document.addEventListener('click', event => {
    if (event.target.closest('#checkoutButton') && completedOrder) {
      setTimeout(() => showConfirmation(completedOrder), 0);
    }
  }, true);

  document.addEventListener('submit', async event => {
    if (event.target !== form) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (completedOrder) {
      showConfirmation(completedOrder);
      return;
    }
    const errorMessage = info.querySelector('.payment-error');
    errorMessage.hidden = true;
    submit.disabled = true;
    submit.textContent = 'Preparando pagamento…';
    try {
      const cart = window.lumiCart || [];
      const response = await fetch('/api/orders', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: cart.map(item => ({ id: item.id })) })
      });
      const raw = await response.text();
      let result;
      try { result = JSON.parse(raw); }
      catch { throw new Error('O servidor respondeu de forma inesperada. Tente novamente.'); }
      if (!response.ok) throw new Error(result.error || 'Não foi possível iniciar o pagamento.');
      if (!result.checkout_url) throw new Error('A InfinitePay não retornou o link de pagamento.');
      completedOrder = result;
      showConfirmation(result);
    } catch (error) {
      errorMessage.textContent = error.message || 'Não foi possível conectar ao servidor.';
      errorMessage.hidden = false;
      submit.disabled = false;
      submit.innerHTML = 'Tentar novamente <span>↗</span>';
    }
  }, true);
})();
