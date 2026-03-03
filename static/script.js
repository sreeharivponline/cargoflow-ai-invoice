// DOM Elements
const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('fileInput');
const browseBtn = document.getElementById('browseBtn');
const loadingOverlay = document.getElementById('loadingOverlay');
const documentViewer = document.getElementById('documentViewer');
const emptyPreview = document.getElementById('emptyPreview');
const connectionStatus = document.getElementById('connectionStatus');

const extractionEmpty = document.getElementById('extractionEmpty');
const extractionCard = document.getElementById('extractionCard');

// Dashboard Elements
const allInvoicesList = document.getElementById('allInvoicesList');
const recentDashboardList = document.getElementById('recentDashboardList');
const dataModal = document.getElementById('dataModal');
const modalTitle = document.getElementById('modalTitle');
const modalContentHtml = document.getElementById('modalContentHtml');

// Form Fields
const valInvoiceNum = document.getElementById('valInvoiceNum');
const valDate = document.getElementById('valDate');
const valCarrier = document.getElementById('valCarrier');
const valType = document.getElementById('valType');
const valTotal = document.getElementById('valTotal');
const valCurrency = document.getElementById('valCurrency');
const lineItemsBody = document.getElementById('lineItemsBody');

// References Raw
const rawJsonPreview = document.getElementById('rawJsonPreview');

let selectedFile = null;
const socket = io();

// Initial Setup
const init = () => {
    setupEventListeners();
    setupSocketListeners();
    fetchInvoices();
};

const fetchInvoices = async () => {
    try {
        const response = await fetch('/api/invoices');
        const invoices = await response.json();
        renderInvoiceList(invoices);
    } catch (e) {
        console.error("Failed to fetch invoices");
    }
};

const renderInvoiceList = (invoices) => {
    allInvoicesList.innerHTML = '';
    recentDashboardList.innerHTML = '';

    if (invoices.length === 0) {
        allInvoicesList.innerHTML = '<p style="color:var(--text-muted); font-size: 0.875rem;">No extractions found.</p>';
        recentDashboardList.innerHTML = '<p style="color:var(--text-muted); font-size: 0.875rem;">No recent extractions found.</p>';
        return;
    }

    invoices.forEach((inv, index) => {
        const div = document.createElement('div');
        div.className = 'single-line-item';
        div.tabIndex = 0;

        div.innerHTML = `
            <div class="line-content">
                <span class="inv-number">${inv.invoice_number || 'Unknown'}</span>
                <span class="inv-carrier">${inv.carrier_name || 'Unknown Carrier'}</span>
            </div>
            <div class="line-end">
                <span class="inv-total">${inv.currency || ''} ${parseFloat(inv.total_amount || 0).toFixed(2)}</span>
                <i data-lucide="external-link" style="width:16px; height:16px; color:var(--text-muted);"></i>
            </div>
        `;

        div.addEventListener('click', () => {
            showModal(inv);
        });

        allInvoicesList.appendChild(div);

        // Dashboard logic (max 3, redirects to all invoices tab)
        if (index < 3) {
            const dashDiv = document.createElement('div');
            dashDiv.className = 'single-line-item';
            dashDiv.tabIndex = 0;
            dashDiv.innerHTML = div.innerHTML;
            dashDiv.addEventListener('click', () => {
                document.querySelector('.side-item[data-target="allInvoicesView"]').click();
            });
            recentDashboardList.appendChild(dashDiv);
        }
    });

    if (window.lucide) {
        lucide.createIcons();
    }
};

window.showModal = (inv) => {
    modalTitle.textContent = `Invoice: ${inv.invoice_number || 'Unknown'} - ${inv.carrier_name || ''}`;

    const d = inv.full_data || {};
    let tableHtml = `
    <div class="table-wrapper" style="margin-bottom: 2rem;">
        <table>
            <tbody>
                <tr><th>Invoice Number</th><td>${d.invoice_number || '-'}</td></tr>
                <tr><th>Invoice Date</th><td>${d.invoice_date || '-'}</td></tr>
                <tr><th>Due Date</th><td>${d.invoice_due_date || '-'}</td></tr>
                <tr><th>Carrier Name</th><td>${d.carrier_name || '-'}</td></tr>
                <tr><th>Transaction Type</th><td>${d.transaction_type || '-'}</td></tr>
                <tr><th>Currency</th><td>${d.currency || '-'}</td></tr>
                <tr><th>Total Amount</th><td><strong>${d.total_amount !== null ? parseFloat(d.total_amount).toFixed(2) : '-'}</strong></td></tr>
                <tr><th>Bill of Lading</th><td>${d.bill_of_lading || '-'}</td></tr>
                <tr><th>Ocean/Sea Waybill</th><td>${(d.sea_waybill || []).join(', ') || '-'}</td></tr>
                <tr><th>Containers</th><td>${(d.container_numbers || []).join(', ') || '-'}</td></tr>
            </tbody>
        </table>
    </div>

    <h4 style="margin-bottom: 1rem; font-size: 1rem; font-weight: 600;">Line Items</h4>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Description</th>
                    <th>Qty</th>
                    <th>Unit/Basis</th>
                    <th>Rate</th>
                    <th>Amount</th>
                </tr>
            </thead>
            <tbody>
    `;

    if (d.line_items && d.line_items.length > 0) {
        d.line_items.forEach(li => {
            tableHtml += `
            <tr>
                <td>${li.description || '-'}</td>
                <td>${li.quantity !== null ? li.quantity : '-'}</td>
                <td>${li.unit || '-'}</td>
                <td>${li.rate !== null ? parseFloat(li.rate).toFixed(2) : '-'}</td>
                <td><strong>${li.amount !== null ? parseFloat(li.amount).toFixed(2) : '-'}</strong></td>
            </tr>`;
        });
    } else {
        tableHtml += `<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">No items</td></tr>`;
    }

    tableHtml += `</tbody></table></div>`;

    modalContentHtml.innerHTML = tableHtml;
    dataModal.classList.remove('hidden');
};

window.closeModal = () => {
    dataModal.classList.add('hidden');
};

const setupEventListeners = () => {
    // Drag and Drop
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    // File Input
    browseBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) handleFileSelection(e.target.files[0]);
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });

    // Sidebar Navigation
    document.querySelectorAll('.side-item[data-target]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            // Update active state
            document.querySelectorAll('.side-item').forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            // Show target view
            const targetId = item.getAttribute('data-target');
            document.querySelectorAll('.view-section').forEach(view => view.classList.add('hidden'));
            document.getElementById(targetId).classList.remove('hidden');
        });
    });
};

window.openDashboard = () => {
    document.querySelector('.side-item[data-target="dashboardView"]').click();
};

window.openInvoiceView = () => {
    document.querySelector('.side-item[data-target="invoiceView"]').click();
};

const setupSocketListeners = () => {
    socket.on('connect', () => {
        connectionStatus.classList.remove('hidden');
        connectionStatus.querySelector('.status-text').textContent = 'Live System Connected';
        connectionStatus.querySelector('.dot').style.backgroundColor = 'var(--success)';
    });

    socket.on('disconnect', () => {
        connectionStatus.classList.remove('hidden');
        connectionStatus.querySelector('.status-text').textContent = 'Disconnected';
        connectionStatus.querySelector('.dot').style.backgroundColor = 'var(--danger)';
    });

    socket.on('status_update', (data) => {
        document.getElementById('loadingText').textContent = data.message || 'Extracting...';
    });

    socket.on('upload_success', (data) => {
        loadingOverlay.classList.add('hidden');
        renderResults(data.data);
        fetchInvoices(); // Refresh dashboard list
    });

    socket.on('upload_error', (data) => {
        loadingOverlay.classList.add('hidden');
        alert(`Extraction Error: ${data.error}`);
    });
};

const handleFileSelection = (file) => {
    const validTypes = ['image/png', 'image/jpeg', 'application/pdf', 'image/webp'];
    const validExts = ['.png', '.jpg', '.jpeg', '.pdf', '.webp'];
    const filename = file.name.toLowerCase();
    const hasValidExt = validExts.some(ext => filename.endsWith(ext));

    if (!validTypes.includes(file.type) && !hasValidExt) {
        alert('Please upload a PDF or image file (PNG, JPG).');
        return;
    }

    if (file.size > 20 * 1024 * 1024) {
        alert('File size exceeds 20MB limit.');
        return;
    }

    selectedFile = file;

    // Show Preview
    showDocumentPreview(file);

    // Start Upload
    startExtraction();
};

const showDocumentPreview = (file) => {
    emptyPreview.classList.add('hidden');
    documentViewer.classList.remove('hidden');
    documentViewer.innerHTML = '';

    const fileURL = URL.createObjectURL(file);
    if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        const iframe = document.createElement('iframe');
        iframe.src = fileURL;
        documentViewer.appendChild(iframe);
    } else {
        const img = document.createElement('img');
        img.src = fileURL;
        documentViewer.appendChild(img);
    }
};

const startExtraction = () => {
    if (!selectedFile) return;

    extractionEmpty.classList.remove('hidden');
    extractionCard.classList.add('hidden');

    // Reset Form Input
    valInvoiceNum.value = '';
    valDate.value = '';
    valCarrier.value = '';
    valType.value = '';
    valTotal.value = '';
    valCurrency.value = '';
    lineItemsBody.innerHTML = '<tr><td colspan="5" class="empty-row">Extracting...</td></tr>';

    loadingOverlay.classList.remove('hidden');

    const reader = new FileReader();
    reader.onload = (e) => {
        const fileBase64 = e.target.result;
        socket.emit('upload_invoice', {
            file: fileBase64,
            filename: selectedFile.name
        });
    };
    reader.onerror = () => {
        loadingOverlay.classList.add('hidden');
        alert('Error reading file.');
    };
    reader.readAsDataURL(selectedFile);
};

const renderResults = (data) => {
    if (!data) return;

    extractionEmpty.classList.add('hidden');
    extractionCard.classList.remove('hidden');

    valInvoiceNum.value = data.invoice_number || '';
    valDate.value = data.invoice_date || '';
    valCarrier.value = data.carrier_name || '';
    valType.value = data.transaction_type || '';
    valTotal.value = data.total_amount ? parseFloat(data.total_amount).toFixed(2) : '';
    valCurrency.value = data.currency || '';

    // Line Items
    lineItemsBody.innerHTML = '';
    if (data.line_items && data.line_items.length > 0) {
        data.line_items.forEach(item => {
            const tr = document.createElement('tr');

            const desc = item.description || '---';
            const qty = item.quantity !== null ? item.quantity : '-';
            const rate = item.rate !== null ? parseFloat(item.rate).toFixed(2) : '-';
            const unitRateStr = `${item.unit ? item.unit + ' / ' : ''}${rate}`;
            const amt = item.amount !== null ? "$" + parseFloat(item.amount).toFixed(2) : '-';

            tr.innerHTML = `
                <td>${desc}</td>
                <td>${qty}</td>
                <td>${unitRateStr}</td>
                <td><strong>${amt}</strong></td>
                <td><i data-lucide="edit-2" style="width:14px;height:14px;color:var(--text-muted)"></i></td>
            `;
            lineItemsBody.appendChild(tr);
        });
    } else {
        lineItemsBody.innerHTML = `<tr><td colspan="5" class="empty-row">No line items detected.</td></tr>`;
    }

    // References JSON
    rawJsonPreview.textContent = JSON.stringify({
        bill_of_lading: data.bill_of_lading,
        house_bill_of_lading: data.house_bill_of_lading,
        sea_waybill: data.sea_waybill,
        mawb: data.mawb,
        hawb: data.hawb,
        container_numbers: data.container_numbers,
        vat_numbers: data.vat_numbers
    }, null, 2);

    lucide.createIcons();
};

// Boot
init();
