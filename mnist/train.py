import argparse
import os
import time
import datetime

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utee import misc
import torch
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable

import dataset
import model
from resnet import resnet18

parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
parser.add_argument('--wd', type=float, default=0.0001, help='weight decay')
parser.add_argument('--batch_size', type=int, default=200, help='input batch size for training (default: 64)')
parser.add_argument('--epochs', type=int, default=3, help='number of epochs to train (default: 10)')
parser.add_argument('--lr', type=float, default=0.01, help='learning rate (default: 1e-3)')
parser.add_argument('--gpu', default=None, help='index of gpus to use')
parser.add_argument('--ngpu', type=int, default=1, help='number of gpus to use')
parser.add_argument('--seed', type=int, default=117, help='random seed (default: 1)')
parser.add_argument('--log_interval', type=int, default=10,  help='how many batches to wait before logging training status')
parser.add_argument('--test_interval', type=int, default=5,  help='how many epochs to wait before another test')
parser.add_argument('--logdir', default='log/default', help='folder to save to the log')
parser.add_argument('--data_root', default='./data', help='folder to save the model')
parser.add_argument('--decreasing_lr', default='80,120', help='decreasing strategy')
args = parser.parse_args()

# 创建带时间戳的唯一日志目录
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
args.logdir = os.path.join(os.path.dirname(__file__), f'log/run_{timestamp}')
misc.logger.init(args.logdir, 'train_log')
print = misc.logger.info

# select gpu
# 仅使用cpu
# args.gpu = misc.auto_select_gpu(utility_bound=0, num_gpu=args.ngpu, selected_gpus=args.gpu)
# args.ngpu = len(args.gpu)
args.gpu = None
args.ngpu = 1

# 确保数据目录存在
if not os.path.exists(args.data_root):
    os.makedirs(args.data_root, exist_ok=True)

# logger
misc.ensure_dir(args.logdir)
print("=================FLAGS==================")
for k, v in args.__dict__.items():
    print('{}: {}'.format(k, v))
print("========================================")

# seed
args.cuda = False
# args.cuda = torch.cuda.is_available()
# torch.manual_seed(args.seed)
# if args.cuda:
#     torch.cuda.manual_seed(args.seed)

# data loader
train_loader, test_loader = dataset.get(batch_size=args.batch_size, data_root=args.data_root, num_workers=0)

# model
# model = model.mnist(input_dims=784, n_hiddens=[256, 256], n_class=10)
model = resnet18(pretrained=False, model_root=None, num_classes=10)
# model = torch.nn.DataParallel(model, device_ids= range(args.ngpu))
# if args.cuda:
#     model.cuda()

# optimizer
optimizer = optim.SGD(model.parameters(), lr=args.lr, weight_decay=args.wd, momentum=0.9)
decreasing_lr = list(map(int, args.decreasing_lr.split(',')))
print('decreasing_lr: ' + str(decreasing_lr))
best_acc, old_file = 0, None
t_begin = time.time()
loss_ls = []
try:
    # ready to go
    for epoch in range(args.epochs):
        model.train()
        if epoch in decreasing_lr:
            optimizer.param_groups[0]['lr'] *= 0.1
        for batch_idx, (data, target) in enumerate(train_loader):
            indx_target = target.clone()
            if args.cuda:
                data, target = data.cuda(), target.cuda()
            data, target = Variable(data), Variable(target)

            optimizer.zero_grad()
            output = model(data)
            loss = F.cross_entropy(output, target)
            loss.backward()
            optimizer.step()

            if batch_idx % args.log_interval == 0 and batch_idx > 0:
                pred = output.data.max(1)[1]  # get the index of the max log-probability
                correct = pred.cpu().eq(indx_target).sum()
                acc = correct * 1.0 / len(data)
                print('Train Epoch: {} [{}/{}] Loss: {:.6f} Acc: {:.4f} lr: {:.2e}'.format(
                    epoch, batch_idx * len(data), len(train_loader.dataset),
                    loss.data, acc, optimizer.param_groups[0]['lr']))
                loss_ls.append((epoch, batch_idx, float(loss.data)))

        elapse_time = time.time() - t_begin
        speed_epoch = elapse_time / (epoch + 1)
        speed_batch = speed_epoch / len(train_loader)
        eta = speed_epoch * args.epochs - elapse_time
        print("Elapsed {:.2f}s, {:.2f} s/epoch, {:.2f} s/batch, ets {:.2f}s".format(
            elapse_time, speed_epoch, speed_batch, eta))
        misc.model_snapshot(model, os.path.join(args.logdir, 'latest.pth'))

        if epoch % args.test_interval == 0:
            model.eval()
            test_loss = 0
            correct = 0
            for data, target in test_loader:
                indx_target = target.clone()
                if args.cuda:
                    data, target = data.cuda(), target.cuda()
                data, target = Variable(data, volatile=True), Variable(target)
                output = model(data)
                test_loss += F.cross_entropy(output, target).data
                pred = output.data.max(1)[1]  # get the index of the max log-probability
                correct += pred.cpu().eq(indx_target).sum()

            test_loss = test_loss / len(test_loader) # average over number of mini-batch
            acc = 100. * correct / len(test_loader.dataset)
            print('\tTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)'.format(
                test_loss, correct, len(test_loader.dataset), acc))
            if acc > best_acc:
                new_file = os.path.join(args.logdir, 'best-{}.pth'.format(epoch))
                misc.model_snapshot(model, new_file, old_file=old_file, verbose=True)
                best_acc = acc
                old_file = new_file

    import pandas as pd
    loss_df = pd.DataFrame(loss_ls, columns=['epoch', 'batch_idx', 'loss'])
    loss_df.to_csv(os.path.join(args.logdir, 'loss.csv'), index=False)
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    print("Total Elapse: {:.2f}, Best Result: {:.3f}%".format(time.time()-t_begin, best_acc))


