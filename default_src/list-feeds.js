'use strict';

const { google } = require('googleapis');
const fs = require('fs');

// initialize the Youtube API library
const youtube = google.youtube('v3');

async function getApiKey() {
    return fs.readFileSync('./apikey.txt', 'utf-8');
}

async function fetchIds(apiKey, srcChannelId) {
    let results = [];
    let nextPageToken = null;

    do {

        const res = await youtube.subscriptions.list({
            "maxResults": 50,
            // "part": "id",
            "part": "snippet",
            "channelId": srcChannelId,
            // "channelId": "UCBR8-60-B28hp2BmDPdntcQ",
            "key": apiKey,
            "pageToken": nextPageToken
        })

        if (!res.data || !res.data.items) {
            throw new exception('something wrong. exit.');
        }

        // res.data.items.forEach(x => results.push(x.id));
        res.data.items.forEach(x => results.push(x.snippet.resourceId.channelId));

        // res.data.items.forEach(x => results.push({
        //     title: x.snippet.title,
        //     channelId: x.snippet.channelId
        // }));

        nextPageToken = res.data.nextPageToken;

    } while (nextPageToken)

    return results;
}

async function genFeedList() {
    const dest = './default_feeds/feeds.txt';
    const appRoot = 'https://www.youtube.com/feeds/videos.xml?channel_id=';
    const srcChannelId = "UCgTB9TyofzQWNnJ7M-QLfDQ"
    const apiKey = await getApiKey();

    const ids = await fetchIds(apiKey, srcChannelId);
    const buffer = ids.sort().map((id) => `${appRoot}${id}`).join('\n');
    fs.writeFileSync(dest, buffer);
}

if (module === require.main) {
    genFeedList().catch(console.error);
}

module.exports = genFeedList;