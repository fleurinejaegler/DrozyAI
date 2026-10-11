// Isolated HTTP transport fixture. No phone/watch connection exists here.
const readline=require('node:readline');
const {createRelayServer}=require('../phone-companion/local-relay/server.cjs');
let seconds=1790000000;
const server=createRelayServer({token:process.env.DROWSY_TEST_TOKEN,now:()=>seconds});
server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:server.address().port})));
readline.createInterface({input:process.stdin}).on('line',line=>{
 seconds=JSON.parse(line).now;
 console.log(JSON.stringify({now:seconds}));
}).on('close',()=>server.close());
