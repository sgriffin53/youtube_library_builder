console.log("BACKGROUND LOADED");
let config = {};

async function loadConfig() {
    const response = await fetch(browser.runtime.getURL("config.txt"));
    const text = await response.text();

    for (const line of text.split("\n")) {
        const trimmed = line.trim();

        if (!trimmed || trimmed.startsWith("#")) continue;

        const [key, ...rest] = trimmed.split("=");
        config[key.trim()] = rest.join("=").trim();
    }
}

const configReady = loadConfig();

browser.runtime.onMessage.addListener((data) => {
    configReady.then(() => {
        fetch(`http://${config.server_ip}:5001/youtube`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(data)
        })
        .then(response => {
            console.log("Flask response:", response.status);
        })
        .catch(error => {
            console.error("Fetch error:", error);
        });
    });

    return true;
});