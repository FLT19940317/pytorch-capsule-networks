import torch
import torch.nn as nn
import torch.optim as optim
from torch.autograd import Variable
import os
from numpy import prod
from datetime import datetime
from model.model import CapsuleNetwork, CapsNet
from model.loss import CapsuleLoss
from time import time

class CapsNetTrainer:
	"""
	Wrapper object for handling training and evaluation
	"""
	def __init__(self, loaders, model='NIPS2017', learning_rate=0.001, lr_decay=0.96, num_classes=10, num_routing=3, loss='margin_loss',
				 use_gpu=torch.cuda.is_available(), multi_gpu=(torch.cuda.device_count() > 1)):
		self.use_gpu = use_gpu
		self.multi_gpu = multi_gpu
		self.model = model

		self.loaders = loaders
		img_shape = self.loaders['train'].dataset[0][0].numpy().shape
		if model == 'ICLR2018':
			in_channels, A, B, C, D, E, r = 1, 64, 8, 16, 16, num_classes, num_routing
			self.net = CapsNet(in_channels, A, B, C, D, E, r, 
							   use_cuda=use_gpu)
		else:
			self.net = CapsuleNetwork(img_shape=img_shape, channels=256, 
									  primary_dim=8, num_classes=num_classes,
									  out_dim=16, num_routing=num_routing, 
									  use_cuda=use_gpu)
		if self.use_gpu:
			if self.multi_gpu:
				self.net = nn.DataParallel(self.net).cuda()
			else:
				self.net = self.net.cuda()
		self.criterion = CapsuleLoss(loss=loss) #
		self.optimizer = optim.Adam(self.net.parameters(), lr=learning_rate)
		self.scheduler = optim.lr_scheduler.ExponentialLR(self.optimizer, gamma=lr_decay)
		# self.scheduler1 = optim.lr_scheduler.ReduceLROnPlateau(self.optimizer, 'max', patience=1)
		print(9*'#', 'PyTorch Model built'.upper(), 9*'#')
		print('Num params:', sum([prod(p.size()) for p in self.net.parameters()]))
	
	def __repr__(self):
		return repr(self.net)

	def train(self, epochs, classes, save_dir, logger):
		print(9*'#', 'Run started'.upper(), 9*'#')
		eye = torch.eye(len(classes))
		if self.use_gpu:
			eye = eye.cuda()

		steps, lambda_, m = len(self.loaders['train']), 0.001, 0.2
		for epoch in range(1, epochs+1):
			for phase in ['train', 'test']:
				print('{}ing...'.format(phase).capitalize())
				if phase == 'train':
					self.net.train()
				else:
					self.net.eval()

				t0 = time()
				running_loss = 0.0
				correct = 0; total = 0
				for i, (images, labels) in enumerate(self.loaders[phase]):
					if phase == 'train' and self.model == 'ICLR2018':
						if lambda_ < 1:
							lambda_ += 2e-1 / steps
						if m < 0.9:
							m += 2e-1 / steps

					t1 = time()
					if self.use_gpu:
						images, labels = images.cuda(), labels.cuda()
					# One-hot encode labels
					labels = eye[labels]

					images, labels = Variable(images), Variable(labels)

					self.optimizer.zero_grad()

					if self.model == 'ICLR2018':
						outputs, reconstructions = self.net(images, lambda_)
					else: # 'NIPS2017'
						outputs, reconstructions = self.net(images)

					loss = self.criterion(outputs, labels, images, reconstructions, m)

					if phase == 'train':
						loss.backward()
						self.optimizer.step()

					running_loss += loss.data[0]

					_, predicted = torch.max(outputs.data, 1)
					_, labels = torch.max(labels.data, 1)
					total += labels.size(0)
					correct += (predicted == labels).sum()
					accuracy = float(correct) / float(total)

					if phase == 'train':
						print('Epoch {}, Batch {}, Loss {}'.format(epoch, i+1, running_loss/(i+1)),
						'Accuracy {} Time {}s'.format(accuracy, round(time()-t1, 3)))
				
				print('{} Epoch {}, Loss {}'.format(phase.upper(), epoch, running_loss/(i+1)),
				'Accuracy {} Time {}s'.format(accuracy, round(time()-t0, 3)))

				if phase == 'train':
					logger['train'].scalar_summary("loss: ", 
	            									running_loss/(i+1), 
	            									epoch)  #
					logger['train'].scalar_summary("accuracy: ", 
	            								  accuracy, 
	            								  epoch)  #
				else:
					logger['test'].scalar_summary("loss: ", 
	            									running_loss/(i+1), 
	            									epoch)  #
					logger['test'].scalar_summary("accuracy: ", 
	            								  accuracy, 
	            								  epoch)  #
			
			self.scheduler.step()
			# self.scheduler1.step(accuracy)  #
			
		now = str(datetime.now()).replace(" ", "-")
		error_rate = round((1-accuracy)*100, 2)
		torch.save(self.net, os.path.join(save_dir, '{}_{}.pth.tar'.format(error_rate, now)))

		class_correct = list(0. for _ in classes)
		class_total = list(0. for _ in classes)
		for images, labels in self.loaders['test']:
			if self.use_gpu:
				images, labels = images.cuda(), labels.cuda()

			if self.model == 'ICLR2018':
				outputs, reconstructions = self.net(Variable(images), lambda_)
			else:  # 'NIPS2017'
				outputs, reconstructions = self.net(Variable(images))

			_, predicted = torch.max(outputs.data, 1)
			c = (predicted == labels).squeeze()
			for i in range(labels.size(0)):
				label = labels[i]
				class_correct[label] += c[i]
				class_total[label] += 1

		for i in range(len(classes)):
			print('Accuracy of %5s : %2d %%' % (
				classes[i], 100 * class_correct[i] / class_total[i]))
