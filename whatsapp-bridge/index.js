/**
 * G.I.D.E.O.N. WhatsApp Bridge
 *
 * Connects to WhatsApp via the WhatsApp Web protocol.
 * Exposes a local REST API on port 3001 that Gideon (poller.py/tools.py) calls.
 *
 * First run: scan the QR code in the terminal or view it via GET /qr
 * WhatsApp > Menu > Linked Devices > Link Device
 * Session saved to .wwebjs_auth/ -- you only scan once.
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');

const PORT = process.env.WA_BRIDGE_PORT || 3001;

let clientReady = false;
let qrData = null;
let lastError = null;

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: '.wwebjs_auth' }),
    puppeteer: {
        headless: true,
        executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-blink-features=AutomationControlled',
            '--no-first-run',
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ],
    },
});

client.on('qr', (qr) => {
    qrData = qr;
    clientReady = false;
    console.log('\n===================================================');
    console.log('  Scan this QR code with WhatsApp on your phone:');
    console.log('  WhatsApp > Settings / Menu > Linked Devices > Link Device');
    console.log('===================================================\n');
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    clientReady = true;
    qrData = null;
    lastError = null;
    console.log('\n[OK] WhatsApp bridge READY\n');
});

client.on('authenticated', () => {
    console.log('[OK] WhatsApp authenticated');
});

client.on('auth_failure', (msg) => {
    lastError = 'Auth failure: ' + msg;
    clientReady = false;
    console.error('[ERR] Auth failed:', msg);
});

client.on('disconnected', async (reason) => {
    clientReady = false;
    lastError = 'Disconnected: ' + reason;
    console.warn('[WARN] Disconnected:', reason);
    try {
        await client.destroy();
    } catch (_) {}
    if (reason !== 'LOGOUT') {
        setTimeout(async () => {
            try {
                console.log('Re-initializing WhatsApp client...');
                await client.initialize();
            } catch (e) {
                console.error('Re-init error:', e);
            }
        }, 5000);
    }
});

process.on('SIGINT', async () => {
    try { await client.destroy(); } catch (_) {}
    process.exit(0);
});

process.on('SIGTERM', async () => {
    try { await client.destroy(); } catch (_) {}
    process.exit(0);
});


function requireReady(res) {
    if (!clientReady) {
        res.status(503).json({
            error: qrData ? 'Scan the QR code first' : (lastError || 'WhatsApp client not ready'),
            qr_pending: !!qrData
        });
        return false;
    }
    return true;
}

function fmtMsg(msg) {
    return {
        id: msg.id._serialized,
        from: msg.from,
        to: msg.to,
        fromMe: msg.fromMe,
        body: msg.body,
        timestamp: msg.timestamp,
        time: new Date(msg.timestamp * 1000).toISOString(),
        type: msg.type,
        hasMedia: msg.hasMedia,
        author: msg.author || null
    };
}

function fmtChat(chat) {
    return {
        id: chat.id._serialized,
        name: chat.name || chat.id.user || 'Unknown',
        isGroup: chat.isGroup,
        unreadCount: chat.unreadCount,
        lastMessage: chat.lastMessage ? {
            body: chat.lastMessage.body,
            fromMe: chat.lastMessage.fromMe,
            time: new Date(chat.lastMessage.timestamp * 1000).toISOString()
        } : null,
        pinned: chat.pinned
    };
}

const app = express();
app.use(express.json());

// Status check
app.get('/status', (req, res) => {
    res.json({
        ready: clientReady,
        qr_pending: !!qrData,
        qr_raw: qrData,
        error: lastError,
        version: '1.0.0'
    });
});

// Visual QR Code Web Page for easy scanning from phone
app.get('/qr', (req, res) => {
    if (clientReady) {
        return res.send(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>WhatsApp Connected - Gideon</title>
                <style>
                    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
                    .card { background: #1e293b; padding: 2.5rem; border-radius: 1rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; max-width: 440px; border: 1px solid #22c55e; }
                    h1 { color: #4ade80; margin: 0 0 1rem 0; }
                    p { color: #94a3b8; font-size: 1rem; line-height: 1.6; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>✅ WhatsApp Connected!</h1>
                    <p>Gideon is paired with your WhatsApp account and ready to read, search, and reply to messages as you.</p>
                </div>
            </body>
            </html>
        `);
    }

    if (!qrData) {
        return res.send(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>Generating QR - Gideon</title>
                <meta http-equiv="refresh" content="3">
                <style>
                    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
                    .card { background: #1e293b; padding: 2rem; border-radius: 1rem; text-align: center; max-width: 400px; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h2>⏳ Initializing WhatsApp...</h2>
                    <p style="color:#94a3b8;">Generating QR code, refreshing automatically in 3 seconds...</p>
                </div>
            </body>
            </html>
        `);
    }

    const qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=' + encodeURIComponent(qrData);
    res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Link WhatsApp to Gideon</title>
            <meta http-equiv="refresh" content="15">
            <style>
                body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
                .card { background: #1e293b; padding: 2rem 2.5rem; border-radius: 1.25rem; box-shadow: 0 15px 30px rgba(0,0,0,0.6); text-align: center; max-width: 440px; border: 1px solid #334155; }
                h1 { margin: 0 0 0.5rem 0; font-size: 1.6rem; color: #38bdf8; }
                p { color: #94a3b8; font-size: 0.95rem; margin: 0.25rem 0 1.25rem 0; }
                .qr-box { background: white; padding: 14px; border-radius: 14px; display: inline-block; margin-bottom: 1.5rem; }
                .qr-box img { display: block; border-radius: 6px; }
                .instructions { text-align: left; background: #0f172a; padding: 1.2rem; border-radius: 10px; font-size: 0.9rem; color: #cbd5e1; border: 1px solid #334155; }
                .instructions ol { margin: 0.5rem 0 0 0; padding-left: 1.3rem; }
                .instructions li { margin-bottom: 0.35rem; }
                .badge { display: inline-block; background: #0369a1; color: #e0f2fe; padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: bold; margin-bottom: 0.75rem; }
            </style>
        </head>
        <body>
            <div class="card">
                <span class="badge">GIDEON MOBILE BRIDGE</span>
                <h1>📱 Link WhatsApp</h1>
                <p>Scan this code once to give Gideon access to reply as you</p>
                <div class="qr-box">
                    <img src="${qrUrl}" alt="WhatsApp QR Code" width="280" height="280" />
                </div>
                <div class="instructions">
                    <strong style="color:#f1f5f9;">How to pair on your phone:</strong>
                    <ol>
                        <li>Open <b>WhatsApp</b></li>
                        <li>Tap <b>Settings</b> (iOS) or <b>⋮ Menu</b> (Android)</li>
                        <li>Tap <b>Linked Devices</b> &gt; <b>Link a Device</b></li>
                        <li>Scan the QR code above with your phone camera</li>
                    </ol>
                </div>
            </div>
        </body>
        </html>
    `);
});


// List recent chats
app.get('/chats', async (req, res) => {
    if (!requireReady(res)) return;
    try {
        const chats = await client.getChats();
        const limit = Math.min(parseInt(req.query.limit, 10) || 50, 200);
        res.json({
            chats: chats.slice(0, limit).map(fmtChat),
            total: chats.length
        });
    } catch (e) {
        console.error('[ERR] getChats error:', e);
        try {
            // Fallback for newer WhatsApp Web clients where getChats() encounters non-standard chat objects
            const contacts = await client.getContacts();
            const recentContacts = contacts
                .filter(c => c.isMyContact || c.name)
                .slice(0, Math.min(parseInt(req.query.limit, 10) || 20, 50))
                .map(c => ({
                    id: c.id._serialized,
                    name: c.name || c.pushname || c.number || 'Unknown',
                    isGroup: c.isGroup || false,
                    unreadCount: 0,
                    lastMessage: null,
                    pinned: false
                }));
            return res.json({ chats: recentContacts, total: recentContacts.length, fallback: true });
        } catch (e2) {
            res.status(500).json({ error: e.message || String(e) });
        }
    }
});

// Search chat by name or phone
app.get('/search', async (req, res) => {
    if (!requireReady(res)) return;
    const q = (req.query.q || '').toLowerCase().trim();
    if (!q) return res.status(400).json({ error: 'Provide ?q=name' });
    try {
        let chats = [];
        try {
            chats = await client.getChats();
            const matches = chats.filter(c => {
                const name = (c.name || '').toLowerCase();
                const id = (c.id._serialized || '').toLowerCase();
                return name.includes(q) || id.includes(q);
            }).slice(0, 20).map(fmtChat);
            return res.json({ results: matches, count: matches.length });
        } catch (_) {
            const contacts = await client.getContacts();
            const matches = contacts.filter(c => {
                const name = (c.name || c.pushname || '').toLowerCase();
                const number = (c.number || '').toLowerCase();
                return name.includes(q) || number.includes(q);
            }).slice(0, 20).map(c => ({
                id: c.id._serialized,
                name: c.name || c.pushname || c.number,
                unreadCount: 0,
                lastMessage: null
            }));
            return res.json({ results: matches, count: matches.length, fallback: true });
        }
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Fetch messages in a chat
app.get('/chats/:chatId/messages', async (req, res) => {
    if (!requireReady(res)) return;
    try {
        const chat = await client.getChatById(req.params.chatId);
        const limit = Math.min(parseInt(req.query.limit, 10) || 20, 100);
        const messages = await chat.fetchMessages({ limit });
        res.json({
            chatId: req.params.chatId,
            chatName: chat.name,
            messages: messages.map(fmtMsg)
        });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Send message to chat or number
app.post('/send', async (req, res) => {
    if (!requireReady(res)) return;
    let { chatId, message } = req.body;
    if (!chatId || !message) {
        return res.status(400).json({ error: 'Provide chatId and message' });
    }
    // Auto-format standard phone number into WhatsApp ID if needed
    if (!chatId.includes('@')) {
        const cleaned = chatId.replace(/[^0-9]/g, '');
        chatId = `${cleaned}@c.us`;
    }
    try {
        const chat = await client.getChatById(chatId);
        const sent = await chat.sendMessage(message);
        res.json({
            ok: true,
            chatId,
            chatName: chat.name,
            message,
            messageId: sent.id._serialized,
            sentAt: new Date().toISOString()
        });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// List contacts
app.get('/contacts', async (req, res) => {
    if (!requireReady(res)) return;
    try {
        const contacts = await client.getContacts();
        const named = contacts
            .filter(c => (c.name && c.name.trim()) || (c.pushname && c.pushname.trim()))
            .map(c => ({
                id: c.id._serialized,
                name: c.name || c.pushname,
                number: c.number,
                isMyContact: c.isMyContact
            }))
            .slice(0, 300);
        res.json({ contacts: named, total: named.length });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.listen(PORT, '127.0.0.1', () => {
    console.log(`\n[START] Gideon WhatsApp Bridge on http://127.0.0.1:${PORT}`);
    console.log(`        Starting WhatsApp client...\n`);
});

client.initialize();
