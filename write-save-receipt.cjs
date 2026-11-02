'use strict';
// Proposed workflow post-save step. Produces a run artifact, NOT another commit.
const fs=require('node:fs');
const crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {eligible}=require('./src/collection-receipt');
function writeSaveReceipt(env=process.env) {
 if(env.SCRAPER_OUTCOME!=='success' || env.SAVE_OUTCOME!=='success' ||
   !/^[0-9a-f]{40}$/.test(env.SAVED_COMMIT || '')) throw new Error('No successful final save');
 const b=execFileSync('git',['show',`${env.SAVED_COMMIT}:data/collection_receipt.json`]);
 const r=JSON.parse(b);
 if(!eligible(r) || r.run_id!==env.GITHUB_RUN_ID || r.run_attempt!==env.GITHUB_RUN_ATTEMPT ||
   r.repository!==env.GITHUB_REPOSITORY) throw new Error('Saved receipt identity/eligibility mismatch');
 return {schema:'boopa-saved-collection-v1',repository:r.repository,run_id:r.run_id,
   scraper_outcome:env.SCRAPER_OUTCOME,save_outcome:env.SAVE_OUTCOME,
   run_attempt:r.run_attempt,tracker_commit:env.SAVED_COMMIT,
   collection_receipt_sha256:crypto.createHash('sha256').update(b).digest('hex')};
}
module.exports={writeSaveReceipt};
if(require.main===module) {
 try {fs.writeFileSync('saved-collection.json',JSON.stringify(writeSaveReceipt())+'\n',{flag:'wx'});}
 catch(e){console.error(e.message);process.exitCode=1;}
}
