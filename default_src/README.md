# default feed list parser

This script generates `../feeds.txt` by reading `raw-d.html` and get youtube channel ids.

## up and run 

Create a `raw-d.html`. You can do this by getting the html of a youtuber's channel page e.g. https://www.youtube.com/user/Google/channels

```
npm install
npm run parse
```

After that, the `../feeds.txt` file will be updated.