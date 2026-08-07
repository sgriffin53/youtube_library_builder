console.log("CONTENT SCRIPT LOADED");


function sendMetadata() {

    if (!window.location.href.includes("/watch")) {
        return;
    }


    let titleElement = document.querySelector("h1.ytd-watch-metadata yt-formatted-string");

    let title = titleElement ? titleElement.innerText.trim() : document.title.replace(" - YouTube", "");

    let descElement = document.querySelector("#description-inline-expander");

    if (!descElement)
        descElement = document.querySelector("#description");

    let description = descElement ? descElement.innerText.trim() : "";


    console.log("Sending metadata:");
    console.log("Title:", title);
    console.log("Description:", description);


    browser.runtime.sendMessage({
        url: window.location.href,
        title: title,
        description: description
    });
}


// Initial page load
sendMetadata();


// Detect YouTube SPA navigation
let lastUrl = location.href;


new MutationObserver(() => {

    if (location.href !== lastUrl) {

        lastUrl = location.href;

        console.log("YouTube navigation detected");

        const oldTitle = document.title;

        let attempts = 0;

        let waitForMetadata = setInterval(() => {

            let titleElement = document.querySelector("h1.ytd-watch-metadata yt-formatted-string");
            let descElement = document.querySelector("#description-inline-expander") || document.querySelector("#description");

            if (document.title !== oldTitle && titleElement && descElement) {
                clearInterval(waitForMetadata);
                sendMetadata();
            }
            attempts++;

            if (attempts > 20) {
                clearInterval(waitForMetadata);
                sendMetadata();
            }

        }, 250);
    }

}).observe(
    document,
    {
        subtree: true,
        childList: true
    }
);