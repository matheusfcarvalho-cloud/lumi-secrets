const accessCard = document.querySelector('#accessCard');
const accessForm = document.querySelector('#accessForm');
const ordersSection = document.querySelector('#ordersSection');
const orderList = document.querySelector('#orderList');
const accessError = document.querySelector('#accessError');
const ordersMessage = document.querySelector('#ordersMessage');
const emailInput = document.querySelector('#adminEmail');
const passwordInput = document.querySelector('#adminPassword');
const accessTitle = document.querySelector('#accessTitle');
const accessDescription = document.querySelector('#accessDescription');
const accessSubmit = document.querySelector('#accessSubmit');
const productForm = document.querySelector('#productForm');
const adminProductList = document.querySelector('#adminProductList');
const adminFeedbackList = document.querySelector('#adminFeedbackList');
const adminCustomerList = document.querySelector('#adminCustomerList');
const paymentSettingsForm = document.querySelector('#paymentSettingsForm');
let accessMode = 'login';
const ADMIN_TAB_KEY = 'lumiAdminTabActive';
const statuses = {received:'Recebido',confirmed:'Confirmado',preparing:'Em preparação',shipped:'Enviado',delivered:'Entregue',cancelled:'Cancelado'};
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
function money(cents) { return (cents / 100).toLocaleString('pt-BR', {style:'currency', currency:'BRL'}); }
function date(value) { return new Date(value).toLocaleString('pt-BR'); }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, credentials:'same-origin', headers:{...(options.headers || {}),'Content-Type':'application/json'}});
  const raw = await response.text();
  let result;
  try { result = JSON.parse(raw); } catch { const contentType = response.headers.get('content-type') || 'sem Content-Type';
    throw new Error(`A rota ${path} respondeu em formato inesperado (HTTP ${response.status}; ${contentType}).`); }
  if (!response.ok) throw new Error(result.error || 'Falha ao consultar o painel.');
  return result;
}
function setAccessMode(mode) {
  accessMode = mode;
  const setup = mode === 'setup';
  accessTitle.textContent = setup ? 'Cadastrar acesso do dono' : 'Acesso administrativo';
  accessDescription.textContent = setup ? 'Crie o e-mail e a senha do dono. O primeiro cadastro só pode ser feito neste computador.' : 'Digite o e-mail e a senha do dono para acessar o painel da loja.';
  accessSubmit.textContent = setup ? 'Cadastrar e entrar' : 'Acessar painel';
  passwordInput.minLength = setup ? 6 : 0;
  passwordInput.autocomplete = setup ? 'new-password' : 'current-password';
}
function addressText(address) {
  if (!address || !address.street) return 'Endereço não informado';
  return `${address.street}, ${address.number}${address.complement ? ` - ${address.complement}` : ''}\n${address.neighborhood}, ${address.city}/${address.state}\nCEP ${address.cep}`;
}
function renderOrders(orders) {
  if (!orders.length) { orderList.innerHTML = '<p class="empty">Ainda não há pedidos.</p>'; return; }
  orderList.innerHTML = orders.map(order => `<article class="order-card"><div class="order-card-head"><div><span class="order-id">PEDIDO ${escapeHtml(order.id)}</span><h3>${escapeHtml(order.customer_name)}</h3><span class="order-date">Criado em ${escapeHtml(date(order.created_at))} · WhatsApp ${escapeHtml(order.whatsapp)}</span></div><span class="status-pill">${escapeHtml(statuses[order.status] || order.status)}</span></div><div class="payment-status"><strong>Pagamento:</strong> ${order.payment_status === 'paid' ? 'Confirmado' : order.payment_status === 'pending' ? 'Aguardando InfinitePay' : order.payment_status === 'link_error' ? 'Falha ao criar cobrança' : 'Não iniciado'}${order.payment_method ? ` · ${order.payment_method === 'pix' ? 'Pix' : 'Cartão de crédito'}` : ''}${order.payment_url ? ` · <a href="${escapeHtml(order.payment_url)}" target="_blank" rel="noopener noreferrer">Abrir checkout</a>` : ''}</div><div class="order-grid"><section><h4>Entrega</h4><p>${escapeHtml(addressText(order.delivery_address))}</p></section><section><h4>Itens</h4><p class="order-items">${order.items.map(item => `${escapeHtml(item.quantity)}× ${escapeHtml(item.product_name)} · ${escapeHtml(item.model)} · ${escapeHtml(money(item.unit_price_cents))}`).join('\n')}<br><span class="total">Total: ${escapeHtml(money(order.total_cents))}</span></p></section></div><form class="status-form" data-order="${escapeHtml(order.id)}"><label>Atualizar status<select name="status">${Object.entries(statuses).map(([value,label]) => `<option value="${value}" ${order.status === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label><button type="submit">Salvar status</button></form><section class="timeline"><h4>Histórico</h4><ol>${order.history.map(event => `<li><strong>${escapeHtml(event.description)}</strong><time>${escapeHtml(date(event.occurred_at))}</time></li>`).join('')}</ol></section></article>`).join('');
}
async function loadOrders() {
  const result = await api('/api/orders');
  renderOrders(result.orders);
  return result.orders.length;
}
function renderProducts(products) {
  if (!products.length) { adminProductList.innerHTML = '<p class="empty">Nenhum produto cadastrado.</p>'; return; }
  adminProductList.innerHTML = products.map(product => `<article class="admin-product-card ${product.active ? '' : 'inactive'}"><img src="${escapeHtml(product.image)}" alt=""><div><h4>${escapeHtml(product.name)}${product.model ? ` · ${escapeHtml(product.model)}` : ''}</h4><p>${escapeHtml(product.type)}${product.label ? ` · ${escapeHtml(product.label)}` : ''}</p><p>${escapeHtml(money(product.price_cents))} · ${product.active ? 'Ativo na loja' : 'Retirado da loja'}</p></div><div class="admin-product-actions"><button type="button" data-edit-product="${product.id}">Editar</button><button type="button" data-toggle-product="${product.id}" data-active="${product.active ? '1' : '0'}">${product.active ? 'Retirar' : 'Reativar'}</button></div></article>`).join('');
}
function renderFeedback(feedbacks) {
  if (!feedbacks.length) { adminFeedbackList.innerHTML = '<p class="empty">Ainda não há feedbacks de clientes.</p>'; return; }
  adminFeedbackList.innerHTML = feedbacks.map(item => { const rating = Math.max(1, Math.min(5, Number(item.rating) || 5)); return `<article class="admin-feedback-card"><h4>${escapeHtml(item.customer_name)}</h4><div class="admin-feedback-stars" aria-label="${rating} de 5 estrelas">${'★'.repeat(rating)}${'☆'.repeat(5-rating)}</div><small>${escapeHtml(item.email)} · ${escapeHtml(date(item.created_at))}</small><p>${escapeHtml(item.message)}</p></article>`; }).join('');
}
async function loadProducts() { const result = await api('/api/admin/products'); renderProducts(result.products); }
async function loadFeedback() { const result = await api('/api/admin/feedback'); renderFeedback(result.feedbacks); }
function renderCustomers(customers) {
  if (!customers.length) { adminCustomerList.innerHTML = '<p class="empty">Ainda não há perfis cadastrados.</p>'; return; }
  adminCustomerList.innerHTML = customers.map(customer => {
    const address = `${customer.street}, ${customer.number}${customer.complement ? ` · ${customer.complement}` : ''} · ${customer.neighborhood}, ${customer.city}/${customer.state} · CEP ${customer.cep}`;
    return `<article class="admin-customer-card"><div><h4>${escapeHtml(customer.name)}</h4><p>${escapeHtml(customer.email)} · WhatsApp ${escapeHtml(customer.whatsapp)}</p><p>${escapeHtml(address)}</p><small>Cadastro: ${escapeHtml(date(customer.created_at))}</small></div><strong>${escapeHtml(customer.order_count)} pedido(s) · ${escapeHtml(money(customer.spent_cents))}</strong></article>`;
  }).join('');
}
async function loadCustomers() { const result = await api('/api/admin/customers'); renderCustomers(result.customers); }
async function loadPaymentSettings() {
  const settings = await api('/api/admin/payment-settings');
  paymentSettingsForm.elements.handle.value = settings.handle;
  paymentSettingsForm.elements.public_url.value = settings.public_url;
  document.querySelector('#paymentSettingsMessage').textContent = settings.configured ? 'InfiniteTag configurada.' : 'Configure a InfiniteTag depois de criar a conta.';
}
async function loadDashboard() {
  try {
    const count = await loadOrders();
    await Promise.all([loadProducts(), loadFeedback(), loadCustomers(), loadPaymentSettings()]);
    ordersMessage.textContent = `${count} pedido(s) registrados`;
    accessCard.hidden = true;
    ordersSection.hidden = false;
  } catch (error) {
    ordersMessage.textContent = '';
    ordersSection.hidden = true;
    accessCard.hidden = false;
    if (error.message.includes('Acesso administrativo')) { passwordInput.value = ''; accessError.textContent = 'Entre com o e-mail e a senha do dono.'; }
    else accessError.textContent = error.message;
  }
}
async function loadAccessStatus() {
  try { const result = await api('/api/admin/status'); setAccessMode(result.setup_allowed ? 'setup' : 'login'); }
  catch (error) { setAccessMode('login'); accessError.textContent = error.message; }
}
function resetProductForm() { productForm.reset(); productForm.elements.id.value = ''; productForm.elements.type.value = 'sutiãs'; document.querySelector('#productFormTitle').textContent = 'Novo produto'; document.querySelector('#productFormMessage').textContent = ''; }
function selectPanel(name) {
  document.querySelectorAll('[data-admin-tab]').forEach(button => button.classList.toggle('active', button.dataset.adminTab === name));
  document.querySelectorAll('[data-admin-panel]').forEach(panel => { panel.hidden = panel.dataset.adminPanel !== name; });
  productForm.hidden = name !== 'products' || !productForm.elements.id.value && productForm.hidden;
}
accessForm.addEventListener('submit', async event => {
  event.preventDefault(); accessError.textContent = ''; accessSubmit.disabled = true;
  const credentials = {email:emailInput.value.trim(), password:passwordInput.value};
  try {
    if (accessMode === 'setup') { await api('/api/admin/setup', {method:'POST', body:JSON.stringify(credentials)}); setAccessMode('login'); }
    await api('/api/admin/login', {method:'POST', body:JSON.stringify(credentials)});
    sessionStorage.setItem(ADMIN_TAB_KEY, 'active'); passwordInput.value = ''; await loadDashboard();
  } catch (error) { passwordInput.value = ''; accessError.textContent = error.message || 'Não foi possível acessar o painel.'; }
  finally { accessSubmit.disabled = false; }
});
document.querySelector('#refreshOrders').addEventListener('click', loadDashboard);
document.querySelector('#logoutAdmin').addEventListener('click', async () => {
  try { await fetch('/api/admin/logout', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'}); }
  finally { sessionStorage.removeItem(ADMIN_TAB_KEY); passwordInput.value = ''; ordersSection.hidden = true; accessCard.hidden = false; accessError.textContent = ''; await loadAccessStatus(); }
});
orderList.addEventListener('submit', async event => {
  const form = event.target.closest('.status-form'); if (!form) return; event.preventDefault();
  const button = form.querySelector('button'); button.disabled = true;
  try { await api(`/api/orders/${encodeURIComponent(form.dataset.order)}/status`, {method:'PATCH', body:JSON.stringify({status:form.elements.status.value})}); await loadDashboard(); }
  catch (error) { ordersMessage.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelectorAll('[data-admin-tab]').forEach(button => button.addEventListener('click', () => selectPanel(button.dataset.adminTab)));
paymentSettingsForm.addEventListener('submit', async event => {
  event.preventDefault(); const message = document.querySelector('#paymentSettingsMessage'); const button = paymentSettingsForm.querySelector('[type="submit"]'); button.disabled = true; message.textContent = 'Salvando...';
  try { const payload = {handle:paymentSettingsForm.elements.handle.value.trim(), public_url:paymentSettingsForm.elements.public_url.value.trim()}; const result = await api('/api/admin/payment-settings', {method:'POST', body:JSON.stringify(payload)}); message.textContent = result.configured ? 'InfinitePay configurada.' : 'InfiniteTag removida.'; }
  catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector('#newProductButton').addEventListener('click', () => { resetProductForm(); productForm.hidden = false; productForm.scrollIntoView({behavior:'smooth', block:'start'}); });
document.querySelector('#cancelProductEdit').addEventListener('click', () => { resetProductForm(); productForm.hidden = true; });
async function uploadProductImage(file) {
  if (file.size > 3 * 1024 * 1024) throw new Error('A foto precisa ter no máximo 3 MB.');
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Não foi possível ler a foto selecionada.'));
    reader.readAsDataURL(file);
  });
  const base64 = String(dataUrl).split(',', 2)[1];
  const result = await api('/api/admin/product-image', {method:'POST', body:JSON.stringify({mime:file.type, data:base64})});
  return result.image;
}
productForm.addEventListener('submit', async event => {
  event.preventDefault(); const message = document.querySelector('#productFormMessage'); const button = productForm.querySelector('[type="submit"]'); button.disabled = true; message.textContent = 'Salvando produto...';
  const data = new FormData(productForm); const id = data.get('id');
  try {
    const selectedFile = data.get('image_file');
    let image = String(data.get('image') || '').trim();
    if (selectedFile && selectedFile.size > 0) { message.textContent = 'Enviando foto...'; image = await uploadProductImage(selectedFile); }
    if (!image) throw new Error('Cole um link de imagem ou escolha uma foto do dispositivo.');
    const payload = {name:data.get('name').trim(), model:data.get('model').trim(), type:data.get('type'), label:data.get('label').trim(), price_cents:Math.round(Number(data.get('price')) * 100), image};
    await api(id ? `/api/admin/products/${encodeURIComponent(id)}` : '/api/admin/products', {method:id ? 'PATCH' : 'POST', body:JSON.stringify(payload)});
    resetProductForm(); productForm.hidden = true; await loadProducts();
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
adminProductList.addEventListener('click', async event => {
  const edit = event.target.closest('[data-edit-product]');
  if (edit) {
    try { const {products} = await api('/api/admin/products'); const product = products.find(item => item.id === Number(edit.dataset.editProduct)); if (!product) return;
      resetProductForm(); productForm.elements.id.value = product.id; productForm.elements.name.value = product.name; productForm.elements.model.value = product.model; productForm.elements.type.value = product.type; productForm.elements.label.value = product.label; productForm.elements.price.value = (product.price_cents / 100).toFixed(2); productForm.elements.image.value = product.image; document.querySelector('#productFormTitle').textContent = 'Editar produto'; productForm.hidden = false; productForm.scrollIntoView({behavior:'smooth', block:'start'});
    } catch (error) { ordersMessage.textContent = error.message; }
    return;
  }
  const toggle = event.target.closest('[data-toggle-product]'); if (!toggle) return; toggle.disabled = true;
  try { await api(`/api/admin/products/${encodeURIComponent(toggle.dataset.toggleProduct)}`, {method:'PATCH', body:JSON.stringify({active:toggle.dataset.active !== '1'})}); await loadProducts(); }
  catch (error) { ordersMessage.textContent = error.message; }
  finally { toggle.disabled = false; }
});
(async () => { if (sessionStorage.getItem(ADMIN_TAB_KEY) !== 'active') { try { await fetch('/api/admin/logout', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'}); } catch {} }
  await loadAccessStatus();
  if (sessionStorage.getItem(ADMIN_TAB_KEY) === 'active') await loadDashboard();
  else { ordersSection.hidden = true; accessCard.hidden = false; accessError.textContent = ''; }
})();
