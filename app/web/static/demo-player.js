'use strict';
(async()=>{
 const video=document.querySelector('#movie');
 const error=document.querySelector('#video-error');
 const chapterBox=document.querySelector('#chapters');
 const transcript=document.querySelector('#transcript');
 const stamp=t=>Math.floor(t/60).toString().padStart(2,'0')+':'+Math.floor(t%60).toString().padStart(2,'0');
 video.addEventListener('error',()=>{error.hidden=false;});
 video.addEventListener('loadeddata',()=>{error.hidden=true;});
 try{
  const response=await fetch('/static/demo-chapters.json');
  if(!response.ok)throw Error('Chapter manifest unavailable');
  const chapters=await response.json();
  if(!Array.isArray(chapters)||!chapters.length||chapters.some(c=>!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.start<0||c.end<=c.start))throw Error('Invalid chapter manifest');
  for(const [index,c] of chapters.entries()){
   const button=document.createElement('button');button.type='button';button.className='chapter';button.disabled=video.readyState<1;
   button.setAttribute('aria-label',stamp(c.start)+'，'+c.title);button.setAttribute('aria-current',index===0?'true':'false');
   const time=document.createElement('time');time.textContent=stamp(c.start);button.append(time,document.createTextNode(c.title));
   button.addEventListener('click',()=>{video.currentTime=c.start;update();video.scrollIntoView({block:'center',behavior:'auto'});video.focus({preventScroll:true});});chapterBox.append(button);
   const article=document.createElement('article'),heading=document.createElement('h3'),copy=document.createElement('p');
   heading.textContent=stamp(c.start)+'　'+c.title;copy.textContent=c.sentences.join('');article.append(heading,copy);transcript.append(article);
  }
  function update(){const t=video.currentTime;const active=chapters.findIndex((c,i)=>t>=c.start&&(t<c.end||i===chapters.length-1));Array.from(chapterBox.children).forEach((b,i)=>b.setAttribute('aria-current',i===active?'true':'false'));}
  video.addEventListener('loadedmetadata',()=>{Array.from(chapterBox.children).forEach(b=>{b.disabled=false;});update();});
  video.addEventListener('timeupdate',update);video.addEventListener('seeked',update);
 }catch(e){chapterBox.textContent='章节暂时未能加载，可直接使用视频进度条。';}
})();
